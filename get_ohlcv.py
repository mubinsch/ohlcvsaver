# get_ohlcv.py

import re
from typing import Dict
from datetime import datetime, timedelta
import requests
import polars as pl



# canonical alias mapping (left side: user input normalized -> right side: LiteFinance symbol)
_LF_ALIAS_MAP: Dict[str, str] = {
    # Dollar index
    "DXY": "USDX",
    "USDX": "USDX",

    # Metals / commodities
    "XAU": "XAUUSD",
    "GOLD": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "XAG": "XAGUSD",
    "SILVER": "XAGUSD",
    "XAGUSD": "XAGUSD",

    # Major FX shorthand -> common LiteFinance tickers
    "EUR": "EURUSD",
    "EURUSD": "EURUSD",
    "GBP": "GBPUSD",
    "GBPUSD": "GBPUSD",
    "AUD": "AUDUSD",
    "AUDUSD": "AUDUSD",
    "NZD": "NZDUSD",
    "NZDUSD": "NZDUSD",
    "CAD": "USDCAD",   # LiteFinance uses USDCAD (USD base)
    "USD": "USD",      # leave as-is (rare to request alone)

    # JPY and CHF are commonly quoted with USD as base on LiteFinance
    "JPY": "USDJPY",   # USD/JPY
    "USDJPY": "USDJPY",
    "CHF": "USDCHF",   # USD/CHF
    "USDCHF": "USDCHF",

    # Cryptos common mapping to USD-based LiteFinance instruments
    "BTC": "BTCUSD",
    "BTCUSD": "BTCUSD",
    "BTCUSD_cl": "BTCUSD_cl",
    "ETH": "ETHUSD",
    "ETHUSD": "ETHUSD",
    "ETHUSD_cl": "ETHUSD_cl",
    "DOGE": "DOGEUSD",
    "DOGEUSD": "DOGEUSD",
    "DOGEUSD_cl": "DOGEUSD_cl",
    "XRP": "XRPUSD",
    "XRPUSD": "XRPUSD",
    "XRPUSD_cl": "XRPUSD_cl",
    "TOTAL": "TOTAL",  # keep as-is if you have an index called TOTAL on your data source

    # Indices / futures shorthand -> LiteFinance naming
    "SPX": "SPX",      # check your group definitions; leave as-is if the exchange uses SPX
    "NQ": "NQ",
    "YM": "YM",
}

def normalize_lf_symbol(symbol: str) -> str:
    """
    Normalize trading symbol for API requests.

    - strip whitespace and slashes, uppercase
    - map common short aliases to LiteFinance instrument codes via ALIAS_MAP
    - if a symbol already looks like an instrument (endswith USD, or is USDX) we
      return it (after uppercasing)
    """
    if not symbol:
        return ""

    s = symbol.strip().upper().replace(" ", "").replace("/", "")

    # quick pass: if symbol already ends with USD or is USDX or TOTAL, keep it
    if s.endswith("USD") or s in {"USDX", "TOTAL"} or s in _LF_ALIAS_MAP.values():
        return s

    # explicit alias lookup (handles XAU, XAG, DXY, BTC, etc.)
    if s in _LF_ALIAS_MAP:
        return _LF_ALIAS_MAP[s]

    # last-resort heuristics:
    # - If it's three letters and matches a common currency code, map to <code>USD
    #   (EUR -> EURUSD, GBP -> GBPUSD, AUD -> AUDUSD), except CHF/JPY handled above.
    if len(s) == 3 and s.isalpha():
        # list where base is the currency itself (EUR, GBP, AUD, NZD)
        base_pairs = {"EUR", "GBP", "AUD", "NZD"}
        if s in base_pairs:
            return f"{s}USD"
        # currencies where USD is base (JPY, CHF) already covered; for others fallback:
        return f"{s}USD"

    # fallback: return uppercase cleaned symbol unchanged
    return s

def parse_timezone_offset(tz_str: str) -> tuple:
    """Parse timezone string like 'utc+3:30' or 'utc-6' into (hours, minutes)."""
    match = re.match(r'utc([+-])(\d+)(?::(\d+))?', tz_str.lower())
    if not match:
        raise ValueError(f"Invalid timezone format: {tz_str}. Expected format: 'utc+H:MM' or 'utc-H:MM'")
    
    sign = 1 if match.group(1) == '+' else -1
    hours = int(match.group(2))
    minutes = int(match.group(3)) if match.group(3) else 0
    
    return sign * hours, sign * minutes




def to_unix(value):
    """
    Convert a time-like value to a Unix timestamp (int seconds).

    Accepts either a single scalar (int, float, str, datetime/date) or a
    pl.Series of such values, and returns a matching type: a plain int for
    scalar input, or a pl.Series of ints for Series input.

    Handles:
      - strings (automatic parsing via str.to_datetime)
      - datetime / date types → .dt.epoch('s')
      - numeric values → assume timestamps; if > 1e12 treat as ms
      - Object columns containing Python datetime / pd.Timestamp
    """
    if value is None:
        return None

    is_scalar = not isinstance(value, pl.Series)
    series = pl.Series([value]) if is_scalar else value
    dtype = series.dtype

    if dtype == pl.Utf8:
        result = series.str.to_datetime(strict=False).dt.epoch("s").cast(pl.Int64)
    elif dtype in (pl.Datetime, pl.Date):
        result = series.dt.epoch("s").cast(pl.Int64)
    elif dtype.is_numeric():
        # ms → s: take series//1000 where > 1e12, else leave as-is
        result = (series // 1000).zip_with(series > 1e12, series).cast(pl.Int64)
    elif dtype == pl.Object:
        result = series.cast(pl.Utf8).str.to_datetime(strict=False).dt.epoch("s").cast(pl.Int64)
    else:
        raise TypeError(f"Unsupported dtype for to_unix: {dtype}")

    return result[0] if is_scalar else result




# === litefinance ===
_LF_URL = "https://my.litefinance.org/chart/get-history" # not in pythonanywhere whitelist
# _LF_URL = "https://lfdata.pmobint.workers.dev/"
_LF_TIMEOUT = 300.0

_client: requests.Session | None = None


def get_lf_client() -> requests.Session:
    global _client
    if _client is None:
        _client = requests.Session()
    return _client


_LF_TF_MAPPING = {
    "1": ("1", None),
    "2": ("1", "2m"),
    "3": ("1", "3m"),
    "5": ("5", None),
    "10": ("5", "10m"),
    "15": ("15", None),
    "30": ("30", None),
    "45": ("15", "45m"),
    "60": ("60", None),
    "120": ("60", "120m"),
    "240": ("240", None),
    "360": ("240", "360m"),
    "480": ("240", "480m"),
    "D": ("D", None),
    "W": ("W", None),
}

_TF_TO_SECONDS = {
    "1": 60,
    "5": 300,
    "15": 900,
    "30": 1800,
    "60": 3600,
    "240": 14400,
    "D": 86400,
    "W": 604800,
}

_LF_KEY_MAP = {"t": "datetime", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
_LF_SCHEMA_OVERRIDES = {"t": pl.Int64, "o": pl.Float64, "h": pl.Float64, "l": pl.Float64, "c": pl.Float64, "v": pl.Float64}


def _fetch_single_lf_symbol(
    symbol: str,
    base_tf: str,
    resample_rule: str | None,
    base_seconds: int,
    max_chunk_seconds: int,
    from_ts: int,
    to_ts: int,
    ohlc_tz: str,
) -> pl.DataFrame:
    """Fetch + clean OHLCV for a single symbol. Returns an empty df on no data."""

    client = get_lf_client()
    norm_symbol = normalize_lf_symbol(symbol)

    all_chunks = []
    current_from = from_ts

    while current_from < to_ts:
        current_to = min(current_from + max_chunk_seconds, to_ts)

        params = {
            "symbol": norm_symbol,
            "resolution": base_tf,
            # "tf": base_tf,
            "from": str(current_from),
            "to": str(current_to),
        }

        res = client.get(_LF_URL, params=params, timeout=_LF_TIMEOUT)
        res.raise_for_status()

        r = res.json().get("data", {})
        if not r or not r.get("t"):
            break

        present = {k: r[k] for k in _LF_KEY_MAP if k in r}
        chunk_df = pl.DataFrame(present, schema_overrides=_LF_SCHEMA_OVERRIDES)
        chunk_df = chunk_df.rename({k: v for k, v in _LF_KEY_MAP.items() if k in chunk_df.columns})
        chunk_df = chunk_df.with_columns(pl.from_epoch("datetime", time_unit="s"))

        all_chunks.append(chunk_df)

        # Prevent overlapping candles between chunks
        current_from = current_to + base_seconds

    if not all_chunks:
        return pl.DataFrame()

    df = pl.concat(all_chunks, how="vertical_relaxed")

    df = (
        df
        .drop_nulls(subset=["open", "high", "low", "close"])
        .sort("datetime")
        .unique(subset=["datetime"], keep="first")
    )

    if resample_rule:
        agg_exprs = [
            pl.col("open").first().alias(f"open_{norm_symbol}"),
            pl.col("high").max().alias(f"high_{norm_symbol}"),
            pl.col("low").min().alias(f"low_{norm_symbol}"),
            pl.col("close").last().alias(f"close_{norm_symbol}"),
        ]

        if "volume" in df.columns:
            agg_exprs.append(pl.col("volume").sum().alias(f"volume_{norm_symbol}"))

        df = (
            df
            .group_by_dynamic("datetime", every=resample_rule)
            .agg(agg_exprs)
            .drop_nulls()
        )

    # Shift the naive UTC-equivalent "datetime" col by the configured tz offset.
    # Done AFTER resampling so resample bucket boundaries stay UTC-aligned.
    tz_hours, tz_minutes = parse_timezone_offset(ohlc_tz)
    tz_offset = timedelta(hours=tz_hours, minutes=tz_minutes)
    df = df.with_columns((pl.col("datetime") + tz_offset).alias("datetime"))

    return df


def get_lf_ohlcv(
    symbol: str | None = None,
    tf: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    ohlc_tz: str = "utc+3:30",

    multi_symbol: bool = False,
    symbols: list[str] | None = None,
):
    """
    Fetch OHLCV data with support for custom timeframes via resampling.
    Handles the 10k candle limit by chunking requests (sequential, simple).
    The returned "datetime" column is shifted by ohlc_tz before being returned.

    Column naming contract:
      - multi_symbol=True: columns are suffixed per-symbol (e.g. "close_BTCUSD")
        and joined into one wide df on "datetime".
      - multi_symbol=False: columns are returned BARE ("open", "high", "low",
        "close", "volume", "datetime"). This is intentional - SmtEngine relies
        on bare columns and does its own suffixing internally. Callers that
        want suffixed single-symbol output (e.g. the /ohlcv/lf route) should
        suffix it themselves after calling this function.
    """

    tf_upper = str(tf).upper()
    base_tf, resample_rule = _LF_TF_MAPPING.get(tf_upper, (tf_upper, None))

    base_seconds = _TF_TO_SECONDS.get(base_tf, 900)
    max_chunk_seconds = 10000 * base_seconds

    to_ts = to_unix(to_date) if to_date else int(datetime.now().timestamp())
    from_ts = to_unix(from_date) if from_date else to_ts - max_chunk_seconds

    try:
        if multi_symbol:
            if not symbols:
                return pl.DataFrame()

            joined = None
            for s in symbols:
                df = _fetch_single_lf_symbol(
                    s, base_tf, resample_rule, base_seconds, max_chunk_seconds, from_ts, to_ts, ohlc_tz
                )
                if df.is_empty():
                    continue

                df = df.rename({c: f"{c}_{s}" for c in df.columns if c != "datetime"})
                joined = df if joined is None else joined.join(df, on="datetime", how="full", coalesce=True)

            if joined is None:
                return pl.DataFrame()

            return joined.sort("datetime")

        return _fetch_single_lf_symbol(
            symbol, base_tf, resample_rule, base_seconds, max_chunk_seconds, from_ts, to_ts, ohlc_tz
        )

    except Exception as e:
        who = symbols if multi_symbol else symbol
        print(f"[LiteFinance] OHLCV error for {who}: {e}")
        return pl.DataFrame()



