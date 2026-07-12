# save_daily_ohlcv.py

import os
from datetime import datetime, timedelta
from get_ohlcv import get_lf_ohlcv

# === CONFIGURATION ===
# SYMBOL = "btc"       
TF = "1"                
TIMEZONE = "utc+3:30"   
assets = ['btc', 'eth', 'xrp', 'sol', 'xau', 'xag', 'aud', 'dxy', 'chf', 'eur', 'gbp']
def main():
    os.makedirs("data/archive", exist_ok=True)
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    for SYMBOL in assets:
        # Fetch the full 24-hour history for the day
        from_date = now - timedelta(hours=24)
        daily_filename = f"data/archive/{SYMBOL}_{TF}m_{today_str}.csv"

        print(f"Fetching daily archive data for {SYMBOL}...")
        df = get_lf_ohlcv(
            symbol=SYMBOL,
            tf=TF,
            from_date=from_date,
            to_date=now,
            ohlc_tz=TIMEZONE
        )

        if df.is_empty():
            print("⚠️ No data returned for daily archive. Skipping.")
            return

        df = df.sort("datetime")
        df.write_csv(daily_filename)
        
        print(f"✅ Saved daily archive: {daily_filename} ({len(df)} rows)")

if __name__ == "__main__":
    main()