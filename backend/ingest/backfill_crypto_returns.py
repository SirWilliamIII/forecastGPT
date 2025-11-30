from datetime import datetime
from typing import Dict

import pandas as pd
import yfinance as yf

from numeric.asset_returns import insert_asset_return

CRYPTO_CONFIG: Dict[str, str] = {
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
    "XMR-USD": "XMR-USD",
}


def backfill_symbol(
    symbol: str,
    yahoo_ticker: str,
    days: int = 365,
    horizon_minutes: int = 1440,
) -> None:
    print(f"[backfill] Fetching {yahoo_ticker} for last {days} days...")

    df = yf.download(
        yahoo_ticker,
        period=f"{days}d",
        interval="1d",
        auto_adjust=False,
        progress=False,
    )

    if df.empty:
        print(f"[backfill] No data returned for {symbol}")
        return

    # Close prices – can be a Series or a DataFrame depending on yfinance
    closes = df["Close"]
    if isinstance(closes, pd.DataFrame):
        closes = closes.iloc[:, 0]

    closes = closes.dropna()

    # Ensure timezone-aware UTC
    if closes.index.tz is None:
        closes.index = closes.index.tz_localize("UTC")
    else:
        closes.index = closes.index.tz_convert("UTC")

    # For each consecutive pair (t0 -> t1) create one return row
    inserted = 0
    for i in range(len(closes) - 1):
        t0 = closes.index[i]
        p0 = float(closes.iloc[i])
        p1 = float(closes.iloc[i + 1])

        if p0 <= 0 or p1 <= 0:
            continue

        as_of: datetime = t0.to_pydatetime()

        insert_asset_return(
            symbol=symbol,
            as_of=as_of,
            horizon_minutes=horizon_minutes,
            price_start=p0,
            price_end=p1,
        )
        inserted += 1

    print(f"[backfill] Inserted ~{inserted} rows for {symbol}")


def main() -> None:
    for symbol, ticker in CRYPTO_CONFIG.items():
        backfill_symbol(symbol, ticker, days=365, horizon_minutes=1440)


if __name__ == "__main__":
    main()

