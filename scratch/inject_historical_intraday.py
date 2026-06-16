import sys
import os
import duckdb
import pandas as pd
from pathlib import Path
from datetime import datetime

# Set up duckdb path
DB_PATH = r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\db\historify.duckdb"
REPO_PATH = r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\scratch\intraday-data"

def inject_data():
    if not os.path.exists(REPO_PATH):
        print(f"Repository not found at {REPO_PATH}")
        return

    print("Connecting to database...")
    con = duckdb.connect(DB_PATH)
    
    # We only want 2016 to 2021
    target_years = ['2016', '2017', '2018', '2019', '2020', '2021']
    
    total_inserted = 0
    
    for year in target_years:
        year_path = os.path.join(REPO_PATH, "main", year) if os.path.exists(os.path.join(REPO_PATH, "main")) else os.path.join(REPO_PATH, year)
        if not os.path.exists(year_path):
            print(f"Directory {year_path} not found. Skipping {year}.")
            continue
            
        print(f"Processing Year: {year}...")
        
        # Collect all NIFTY.txt files
        nifty_files = []
        for root, dirs, files in os.walk(year_path):
            for file in files:
                if file.upper() == "NIFTY.TXT":
                    nifty_files.append(os.path.join(root, file))
                    
        for file_path in nifty_files:
            try:
                # Read CSV
                df = pd.read_csv(
                    file_path,
                    header=None,
                    names=["Symbol", "Date", "Time", "Open", "High", "Low", "Close", "Volume", "OI"],
                    dtype={"Date": str, "Time": str}
                )
                
                if df.empty:
                    continue
                    
                # Clean strings
                df["Date"] = df["Date"].astype(str).str.strip()
                df["Time"] = df["Time"].astype(str).str.strip()
                
                # Try multiple date formats: YYYYMMDD or YYYY-MM-DD
                def parse_timestamp(row):
                    d = row["Date"]
                    t = row["Time"]
                    # handle seconds if present (HH:MM:SS or HH:MM)
                    fmt_d = "%Y%m%d" if len(d) == 8 else "%Y-%m-%d"
                    fmt_t = "%H:%M:%S" if len(t.split(":")) == 3 else "%H:%M"
                    
                    dt_str = f"{d} {t}"
                    try:
                        dt = datetime.strptime(dt_str, f"{fmt_d} {fmt_t}")
                        return int(dt.timestamp())
                    except:
                        return None
                        
                df["timestamp"] = df.apply(parse_timestamp, axis=1)
                df = df.dropna(subset=["timestamp"])
                
                # Add schema columns
                df["symbol"] = "NIFTY"
                df["exchange"] = "NSE_INDEX"
                df["interval"] = "1m"
                df["open"] = pd.to_numeric(df["Open"], errors="coerce")
                df["high"] = pd.to_numeric(df["High"], errors="coerce")
                df["low"] = pd.to_numeric(df["Low"], errors="coerce")
                df["close"] = pd.to_numeric(df["Close"], errors="coerce")
                df["volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(int)
                df["oi"] = pd.to_numeric(df["OI"], errors="coerce").fillna(0).astype(int)
                
                df = df.dropna(subset=["open", "high", "low", "close"])
                
                if df.empty:
                    continue
                    
                # Select only columns needed for DB
                df_ins = df[["symbol", "exchange", "interval", "timestamp", "open", "high", "low", "close", "volume", "oi"]]
                
                # Insert OR IGNORE using DuckDB
                # DuckDB ON CONFLICT DO NOTHING requires primary key
                con.execute("""
                    INSERT INTO market_data (symbol, exchange, interval, timestamp, open, high, low, close, volume, oi)
                    SELECT * FROM df_ins 
                    ON CONFLICT (symbol, exchange, interval, timestamp) DO NOTHING
                """)
                
                total_inserted += len(df_ins)
                print(f"  Processed {os.path.basename(file_path)}: +{len(df_ins)} rows")
                
            except Exception as e:
                print(f"  Error processing {file_path}: {e}")
                
    print(f"Finished. Total NIFTY 1-min rows inserted: {total_inserted}")
    con.close()

if __name__ == "__main__":
    inject_data()
