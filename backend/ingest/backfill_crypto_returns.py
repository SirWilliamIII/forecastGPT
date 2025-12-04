# backend/ingest/backfill_crypto_returns.py
import os
import sys
import time
from datetime import datetime
from typing import Dict

import pandas as pd
import yfinance as yf

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from numeric.asset_returns import insert_asset_return
from ingest.status import update_ingest_status
from config import get_crypto_symbols, MAX_DOWNLOAD_RETRIES


def backfill_symbol(
    symbol: str,
    yahoo_ticker: str,
    days: int = 365,
    horizon_minutes: int = 1440,
) -> int:
    print(f"[backfill] Fetching {yahoo_ticker} for last {days} days...")

    df = None
    last_error: Exception | None = None

    for attempt in range(MAX_DOWNLOAD_RETRIES):
        try:
            df = yf.download(
                yahoo_ticker,
                period=f"{days}d",
                interval="1d",
                auto_adjust=False,
                progress=False,
            )
            if df is not None and not df.empty:
                break
        except Exception as e:
            last_error = e
            if attempt < MAX_DOWNLOAD_RETRIES - 1:
                delay = 2 ** attempt
                print(f"[backfill] Error downloading {yahoo_ticker} ({e}); retrying in {delay}s...")
                time.sleep(delay)

    if df is None or df.empty:
        print(f"[backfill] No data returned for {symbol} after {MAX_DOWNLOAD_RETRIES} attempts. Last error: {last_error}")
        return 0

    closes = df["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes.iloc[:, 0]

    closes = closes.dropna()

    if closes.index.tz is None:
        closes.index = closes.index.tz_localize("UTC")
    else:
        closes.index = closes.index.tz_convert("UTC")

    inserted = 0
    for i in range(len(closes) - 1):
        t0 = closes.index[i]
        p0 = float(closes.iloc[i])
        p1 = float(closes.iloc[i + 1])

        if p0 <= 0 or p1 <= 0:
            continue

        as_of: datetime = t0.to_pydatetime()

        try:
            insert_asset_return(
                symbol=symbol,
                as_of=as_of,
                horizon_minutes=horizon_minutes,
                price_start=p0,
                price_end=p1,
            )
            inserted += 1
        except ValueError as e:
            print(f"[backfill] Skipping invalid data point at {as_of}: {e}")
            continue

    print(f"[backfill] Inserted ~{inserted} rows for {symbol}")
    return inserted


def main() -> None:
    total_inserted = 0
    crypto_symbols = get_crypto_symbols()
    for symbol, ticker in crypto_symbols.items():
        total_inserted += backfill_symbol(symbol, ticker, days=365, horizon_minutes=1440)

    # Update ingest status
    update_ingest_status("crypto_backfill", total_inserted)


if __name__ == "__main__":
    main()
