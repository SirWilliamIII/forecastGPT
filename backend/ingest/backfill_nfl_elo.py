# backend/ingest/backfill_nfl_elo.py
# Example sports ingestion using FiveThirtyEight NFL Elo data.

import os
import time
from datetime import timezone
from typing import Dict, Iterable, List

import pandas as pd

from numeric.asset_returns import insert_asset_return

ELO_CSV_URL = os.getenv(
    "NFL_ELO_URL", "https://projects.fivethirtyeight.com/nfl-api/nfl_elo.csv"
)
NFL_TEAM_CONFIG: Dict[str, List[str]] = {
    # target_id -> list of acceptable team abbreviations in the dataset
    "NFL:KC_CHIEFS": ["KC", "KAN"],
}

DEFAULT_HORIZON_MINUTES = int(os.getenv("NFL_ELO_HORIZON_MINUTES", str(24 * 60)))
MAX_DOWNLOAD_RETRIES = int(os.getenv("MAX_DOWNLOAD_RETRIES", "3"))


def _load_elo_frame(url: str) -> pd.DataFrame:
    """Fetch the Elo CSV with retry/backoff."""
    last_error: Exception | None = None
    for attempt in range(MAX_DOWNLOAD_RETRIES):
        try:
            df = pd.read_csv(url)
            if df is not None and not df.empty:
                return df
        except Exception as e:
            last_error = e
            if attempt < MAX_DOWNLOAD_RETRIES - 1:
                delay = 2**attempt
                print(f"[nfl_elo] Error fetching Elo CSV ({e}); retrying in {delay}s...")
                time.sleep(delay)
    raise RuntimeError(f"Failed to fetch Elo CSV after retries: {last_error}")


def _select_team_rows(df: pd.DataFrame, team_abbrs: Iterable[str]) -> pd.DataFrame:
    return df[(df["team1"].isin(team_abbrs)) | (df["team2"].isin(team_abbrs))]


def _parse_game_timestamp(date_value) -> pd.Timestamp:
    ts = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(ts):
        return ts
    if ts.tzinfo is None or ts.tz is None:
        ts = ts.tz_localize(timezone.utc)
    else:
        ts = ts.tz_convert(timezone.utc)
    return ts


def backfill_team(symbol: str, team_abbrs: List[str], horizon_minutes: int) -> None:
    df = _load_elo_frame(ELO_CSV_URL)
    df = _select_team_rows(df, team_abbrs)

    if df.empty:
        print(f"[nfl_elo] No rows found for {symbol} using abbreviations {team_abbrs}")
        return

    df = df.sort_values("date")

    inserted = 0
    for row in df.itertuples(index=False):
        # Determine whether the team is in the home/away slot
        if row.team1 in team_abbrs:
            start = getattr(row, "elo1_pre", None)
            end = getattr(row, "elo1_post", None)
        elif row.team2 in team_abbrs:
            start = getattr(row, "elo2_pre", None)
            end = getattr(row, "elo2_post", None)
        else:
            continue

        if start is None or end is None:
            continue
        if pd.isna(start) or pd.isna(end):
            continue
        if start <= 0 or end <= 0:
            continue

        ts = _parse_game_timestamp(getattr(row, "date", None))
        if pd.isna(ts):
            continue

        insert_asset_return(
            symbol=symbol,
            as_of=ts.to_pydatetime(),
            horizon_minutes=horizon_minutes,
            price_start=float(start),
            price_end=float(end),
        )
        inserted += 1

    print(f"[nfl_elo] Inserted ~{inserted} rows for {symbol}")


def main() -> None:
    for symbol, abbrs in NFL_TEAM_CONFIG.items():
        backfill_team(symbol, abbrs, horizon_minutes=DEFAULT_HORIZON_MINUTES)


if __name__ == "__main__":
    main()
