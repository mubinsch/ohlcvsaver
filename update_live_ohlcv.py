# update_live_ohlcv.py

import os
from datetime import datetime, timedelta
import polars as pl
from get_ohlcv import get_lf_ohlcv

# === CONFIGURATION ===
SYMBOL = "XAUUSD"       
TF = "1"                
TIMEZONE = "utc+3:30"   
LIVE_WINDOW_ROWS = 1440 # 24 hours of 1m data
FETCH_LOOKBACK_MINS = 5 # Fetch last 5 mins to catch up safely

def main():
    os.makedirs("data/live", exist_ok=True)
    
    now = datetime.now()
    live_filename = f"data/live/{SYMBOL}_{TF}m_LIVE.csv"

    # Fetch just the most recent data
    from_date = now - timedelta(minutes=FETCH_LOOKBACK_MINS)
    
    print(f"Fetching live feed update for {SYMBOL}...")
    new_df = get_lf_ohlcv(
        symbol=SYMBOL,
        tf=TF,
        from_date=from_date,
        to_date=now,
        ohlc_tz=TIMEZONE
    )

    if new_df.is_empty():
        print("⚠️ No new live data. Skipping.")
        return

    new_df = new_df.sort("datetime")

    # Append to LIVE file
    if os.path.exists(live_filename):
        old_df = pl.read_csv(live_filename, try_parse_dates=True)
        # Concatenate, drop duplicates, sort, and keep only the last 1440 rows
        live_df = (
            pl.concat([old_df, new_df])
            .unique(subset=["datetime"], keep="last")
            .sort("datetime")
            .tail(LIVE_WINDOW_ROWS)
        )
    else:
        live_df = new_df.tail(LIVE_WINDOW_ROWS)

    live_df.write_csv(live_filename)
    print(f"✅ Updated LIVE feed: {live_filename} ({len(live_df)} rows)")

if __name__ == "__main__":
    main()