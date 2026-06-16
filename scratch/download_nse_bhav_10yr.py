"""
NSE F&O Bhav Copy Downloader — 10 Years (2016-01-01 to 2026-12-31)
Downloads daily ATM NIFTY straddle premiums and stores in DuckDB.

Run: python scratch/download_nse_bhav_10yr.py
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import requests
import zipfile
import io
import time
import duckdb
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*',
    'Referer': 'https://www.nseindia.com/',
}

DB_PATH = r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\db\historify.duckdb"
START_DATE = date(2016, 1, 1)
END_DATE   = date(2026, 12, 31)
SYMBOLS    = ["NIFTY"]

# Nifty approximate spot by year (for ATM seed when no spot data available)
APPROX_SPOTS = {
    2016: 8000, 2017: 9500, 2018: 10500, 2019: 11500, 2020: 12000,
    2021: 16000, 2022: 17500, 2023: 19500, 2024: 21500, 2025: 23500, 2026: 24000
}


def init_db(con: duckdb.DuckDBPyConnection):
    con.execute("""
        CREATE TABLE IF NOT EXISTS options_daily_premiums (
            date            DATE      NOT NULL,
            symbol          VARCHAR   NOT NULL,
            expiry_dt       DATE,
            spot_open       DOUBLE,
            atm_strike      DOUBLE,
            ce_open         DOUBLE,
            pe_open         DOUBLE,
            ce_close        DOUBLE,
            pe_close        DOUBLE,
            straddle_open   DOUBLE,
            straddle_close  DOUBLE,
            dte             INTEGER,
            iv_proxy        DOUBLE,
            PRIMARY KEY (date, symbol)
        )
    """)
    print("Table 'options_daily_premiums' ready.")


def get_spot(con: duckdb.DuckDBPyConnection, symbol: str, dt: date) -> float | None:
    """Try to get Nifty spot open from the local market_data table."""
    try:
        exchange = "NSE_INDEX" if symbol == "NIFTY" else ("BSE_INDEX" if symbol == "SENSEX" else "NSE_INDEX")
        ts_start = int(pd.Timestamp(dt).timestamp())
        ts_end   = ts_start + 3600  # first hour of the day
        row = con.execute(
            "SELECT open FROM market_data WHERE symbol=? AND exchange=? AND interval='1m' AND timestamp BETWEEN ? AND ? ORDER BY timestamp LIMIT 1",
            [symbol, exchange, ts_start, ts_end]
        ).fetchone()
        return float(row[0]) if row else None
    except Exception:
        return None


def download_bhav(dt: date) -> pd.DataFrame | None:
    """Download F&O Bhav Copy for a trading date."""
    day = dt.strftime("%d")
    mon = dt.strftime("%b").upper()
    year = dt.strftime("%Y")
    # For dates before mid-2021, the NSE archives URL might slightly differ or follow the same structure.
    # The historical URL structure has been consistent for decades:
    url = f"https://archives.nseindia.com/content/historical/DERIVATIVES/{year}/{mon}/fo{day}{mon}{year}bhav.csv.zip"
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = z.namelist()[0]
                with z.open(name) as f:
                    df = pd.read_csv(f)
            return df
        elif r.status_code == 404:
            return None  # Holiday / non-trading day
        else:
            print(f"    HTTP {r.status_code} for {dt}")
            return None
    except Exception as e:
        print(f"    Error {dt}: {e}")
        return None


def extract_atm(bhav_df: pd.DataFrame, symbol: str, spot: float, dt: date) -> dict | None:
    """Extract ATM straddle premium row from bhav copy dataframe."""
    opts = bhav_df[
        (bhav_df['INSTRUMENT'].str.strip() == 'OPTIDX') &
        (bhav_df['SYMBOL'].str.strip() == symbol)
    ].copy()
    
    if opts.empty:
        return None

    opts['EXPIRY_DT'] = pd.to_datetime(opts['EXPIRY_DT'].str.strip(), format='%d-%b-%Y', errors='coerce')
    opts = opts.dropna(subset=['EXPIRY_DT'])
    
    # Nearest weekly expiry
    future_expiries = opts[opts['EXPIRY_DT'].dt.date >= dt]['EXPIRY_DT']
    if future_expiries.empty:
        return None
    nearest_expiry = future_expiries.min()
    opts = opts[opts['EXPIRY_DT'] == nearest_expiry]

    # ATM strike
    strikes = opts['STRIKE_PR'].unique()
    if len(strikes) == 0:
        return None
    atm_strike = min(strikes, key=lambda s: abs(s - spot))
    
    # Try exact strike, then adjacent
    sorted_strikes = sorted(strikes, key=lambda s: abs(s - spot))
    for s in sorted_strikes[:5]:
        ce_row = opts[(opts['STRIKE_PR'] == s) & (opts['OPTION_TYP'].str.strip() == 'CE')]
        pe_row = opts[(opts['STRIKE_PR'] == s) & (opts['OPTION_TYP'].str.strip() == 'PE')]
        if not ce_row.empty and not pe_row.empty:
            atm_strike = s
            break
    else:
        return None
    
    ce = ce_row.iloc[0]
    pe = pe_row.iloc[0]
    
    dte = (nearest_expiry.date() - dt).days
    straddle_open = float(ce['OPEN']) + float(pe['OPEN'])
    # IV proxy: straddle_price / (spot * sqrt(DTE/365)) * 100
    iv_proxy = (straddle_open / (spot * (max(dte, 1) / 365) ** 0.5) * 100) if dte > 0 else None
    
    return {
        "date":           dt,
        "symbol":         symbol,
        "expiry_dt":      nearest_expiry.date(),
        "spot_open":      spot,
        "atm_strike":     atm_strike,
        "ce_open":        float(ce['OPEN']),
        "pe_open":        float(pe['OPEN']),
        "ce_close":       float(ce['CLOSE']),
        "pe_close":       float(pe['CLOSE']),
        "straddle_open":  round(straddle_open, 2),
        "straddle_close": round(float(ce['CLOSE']) + float(pe['CLOSE']), 2),
        "dte":            dte,
        "iv_proxy":       round(iv_proxy, 2) if iv_proxy else None,
    }


def run():
    # Ensure db directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    con = duckdb.connect(DB_PATH)
    init_db(con)
    
    # Check what we already have
    existing = set()
    try:
        rows = con.execute("SELECT date, symbol FROM options_daily_premiums WHERE symbol='NIFTY'").fetchall()
        existing = {(r[0], r[1]) for r in rows}
        print(f"Already have {len(existing)} rows in DB. Skipping those dates.")
    except Exception:
        pass
    
    # All calendar dates in range
    all_dates = []
    d = START_DATE
    while d <= END_DATE:
        if d.weekday() < 5:  # Mon-Fri only
            all_dates.append(d)
        d += timedelta(days=1)
    
    total = len(all_dates)
    downloaded = 0
    skipped = 0
    errors = 0
    
    print(f"Processing {total} trading days from {START_DATE} to {END_DATE}...\n")
    
    for i, dt in enumerate(all_dates):
        # Skip if already in DB
        if (dt, "NIFTY") in existing:
            skipped += 1
            if i % 100 == 0:
                print(f"Skipped up to {dt}...")
            continue
        
        # Download bhav copy
        bhav_df = download_bhav(dt)
        if bhav_df is None:
            continue
        
        # Get spot
        nifty_spot = get_spot(con, "NIFTY", dt) or APPROX_SPOTS.get(dt.year, 20000)
        
        rows_to_insert = []
        result = extract_atm(bhav_df, "NIFTY", nifty_spot, dt)
        if result:
            rows_to_insert.append(result)
        
        if rows_to_insert:
            df_ins = pd.DataFrame(rows_to_insert)
            con.execute("INSERT OR REPLACE INTO options_daily_premiums SELECT * FROM df_ins")
            downloaded += len(rows_to_insert)
        
        progress = (i + 1) / total * 100
        symbols_done = ", ".join(f"{r['symbol']}:{r['straddle_open']:.0f}" for r in rows_to_insert) if rows_to_insert else "no data"
        print(f"[{progress:5.1f}%] {dt}  |  {symbols_done}")
        
        # Rate limit — be polite to NSE servers
        time.sleep(0.5)
    
    con.close()
    print(f"\nDone. Downloaded: {downloaded} rows, Skipped: {skipped}, Errors: {errors}")
    
    # Print summary
    con2 = duckdb.connect(DB_PATH, read_only=True)
    summary = con2.execute("""
        SELECT symbol, 
               COUNT(*) as days,
               MIN(date) as from_date,
               MAX(date) as to_date,
               ROUND(AVG(straddle_open), 0) as avg_straddle,
               ROUND(MIN(straddle_open), 0) as min_straddle,
               ROUND(MAX(straddle_open), 0) as max_straddle
        FROM options_daily_premiums
        WHERE symbol = 'NIFTY'
        GROUP BY symbol
        ORDER BY symbol
    """).fetchdf()
    print("\n=== Summary ===")
    print(summary.to_string(index=False))
    con2.close()


if __name__ == "__main__":
    run()
