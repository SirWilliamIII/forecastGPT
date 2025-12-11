"""
SportsData.io NFL Event Ingestion

Fetches NFL news and injury events from SportsData.io API and ingests them
into the events table with semantic embeddings for event-based forecasting.

This module provides three phases:
    1. News Event Ingestion - Fetch team news (especially injury reports)
    2. Game-Event Alignment Validation - Verify event coverage for games
    3. Event Enrichment (optional) - Supplement with structured injury data

Usage:
    # Backfill Cowboys and Chiefs injury news
    python -m ingest.sportsdata_events --teams DAL KC

    # Validation report only
    python -m ingest.sportsdata_events --validate-only

    # Full run with all teams
    python -m ingest.sportsdata_events --all-teams

Author: Claude Code
Date: December 2025
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple, Set, Optional
from uuid import uuid4
from dateutil.parser import parse as parse_date

# Add parent directory to path for imports
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from embeddings import embed_text
from config import NFL_EVENT_BACKFILL_START
from utils.sportsdata_api import SportsDataClient, SportsDataAPIError, SportsDataRateLimitError
from signals.nfl_features import get_historical_events_for_games

# Default NFL teams to backfill
DEFAULT_TEAMS = ["DAL", "KC", "SF", "PHI", "BUF", "DET"]

# Team abbreviation to symbol mapping
TEAM_ABBR_TO_SYMBOL = {
    "DAL": "NFL:DAL_COWBOYS",
    "KC": "NFL:KC_CHIEFS",
    "SF": "NFL:SF_49ERS",
    "PHI": "NFL:PHI_EAGLES",
    "BUF": "NFL:BUF_BILLS",
    "DET": "NFL:DET_LIONS",
}


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: News Event Ingestion
# ═══════════════════════════════════════════════════════════════════════

def fetch_news_by_date_range(
    client: SportsDataClient,
    start_date: datetime,
    end_date: datetime,
    team_filter: Optional[List[str]] = None,
    filter_categories: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Fetch news articles for a date range.

    Iterates through dates and fetches news day-by-day using NewsByDate endpoint.
    This is necessary because the general News endpoint only returns 4-5 recent items.

    Args:
        client: SportsDataClient instance
        start_date: Start date for fetching (inclusive)
        end_date: End date for fetching (inclusive)
        team_filter: Optional list of team abbreviations to filter (e.g., ["DAL", "KC"])
        filter_categories: Optional list of categories to filter (e.g., ["Injuries"])

    Returns:
        List of news article dictionaries (deduplicated by NewsID)
    """
    print(f"\n[sportsdata] Fetching news from {start_date.date()} to {end_date.date()}...")

    all_news = {}  # Dict to deduplicate by NewsID
    current_date = start_date

    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")

        try:
            daily_news = client.get_news_by_date(date_str)
            print(f"[sportsdata]   {date_str}: {len(daily_news)} items", end="")

            # Filter by team if specified
            if team_filter:
                daily_news = [item for item in daily_news if item.get("Team") in team_filter]
                print(f" → {len(daily_news)} after team filter", end="")

            # Filter by categories if specified
            if filter_categories:
                filtered = []
                for item in daily_news:
                    categories_str = item.get("Categories", "")
                    if any(cat in categories_str for cat in filter_categories):
                        filtered.append(item)
                daily_news = filtered
                print(f" → {len(daily_news)} after category filter", end="")

            # Add to deduplicated collection
            for item in daily_news:
                news_id = item.get("NewsID")
                if news_id and news_id not in all_news:
                    all_news[news_id] = item

            print()  # Newline

        except SportsDataRateLimitError as e:
            print(f"\n[sportsdata] ✗ Rate limit error: {e}")
            print(f"[sportsdata] Stopping at {date_str}")
            break
        except SportsDataAPIError as e:
            print(f" ✗ API error: {e}")
            # Continue to next date
        except Exception as e:
            print(f" ✗ Error: {e}")
            # Continue to next date

        # Move to next date
        current_date += timedelta(days=1)

        # Small delay to avoid rate limiting (conservative: 0.5s between requests)
        time.sleep(0.5)

    total_items = len(all_news)
    print(f"\n[sportsdata] Total unique items collected: {total_items}")

    return list(all_news.values())


def get_existing_news_ids(news_ids: List[int]) -> Set[int]:
    """
    Batch check which SportsData NewsIDs already exist in database.

    Args:
        news_ids: List of NewsID integers

    Returns:
        Set of existing NewsIDs
    """
    if not news_ids:
        return set()

    # Check by meta->>'news_id' in events table
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Use JSONB query to find events with matching news_id in meta
            cur.execute(
                """
                SELECT (meta->>'news_id')::int as news_id
                FROM events
                WHERE meta ? 'news_id'
                  AND (meta->>'news_id')::int = ANY(%s)
                """,
                (news_ids,)
            )
            return {row["news_id"] for row in cur.fetchall()}


def prepare_news_event(news_item: Dict, team_abbr: str) -> Tuple[uuid4, List, List[float], Dict]:
    """
    Prepare a news item for insertion as an event.

    Args:
        news_item: News article dictionary from SportsData.io
        team_abbr: Team abbreviation

    Returns:
        Tuple of (event_id, postgres_values, vector, vector_metadata)
    """
    event_id = uuid4()

    # Parse timestamp
    updated_str = news_item.get("Updated", "")
    if updated_str:
        timestamp = parse_date(updated_str)
        # Ensure timezone-aware UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
    else:
        timestamp = datetime.now(timezone.utc)

    # Extract fields
    title = news_item.get("Title", "") or ""
    content = news_item.get("Content", "") or ""
    summary = content[:500] if len(content) > 500 else content  # First 500 chars
    raw_text = content
    clean_text = content
    source = f"SportsData.io - {news_item.get('Source', 'Unknown')}"
    source_url = news_item.get("Url", "")

    # Categories: Always include 'sports', 'nfl', and parsed categories
    categories = ["sports", "nfl"]
    categories_str = news_item.get("Categories", "")
    if categories_str:
        # Split on comma, lowercase, and add to list
        parsed_cats = [cat.strip().lower() for cat in categories_str.split(",")]
        categories.extend(parsed_cats)

    # Tags: Team abbreviation and player name if available
    tags = [team_abbr.lower()]

    # Add team symbol tag
    if team_abbr in TEAM_ABBR_TO_SYMBOL:
        tags.append(TEAM_ABBR_TO_SYMBOL[team_abbr].lower())

    # Metadata: Store NewsID, PlayerID for deduplication and reference
    meta = {
        "news_id": news_item.get("NewsID"),
        "player_id": news_item.get("PlayerID"),
        "team_id": news_item.get("TeamID"),
        "original_source": news_item.get("OriginalSource"),
    }

    # Generate embedding
    text_to_embed = clean_text or title or summary
    print(f"[sportsdata] Embedding: {title[:60]}...")
    embed_vector = embed_text(text_to_embed)
    embed_literal = "[" + ",".join(str(x) for x in embed_vector) + "]"

    # Prepare PostgreSQL values
    from psycopg.types.json import Jsonb
    values = [
        event_id,
        timestamp,
        source,
        source_url,
        title,
        summary,
        raw_text,
        clean_text,
        categories,
        tags,
        embed_literal,
        Jsonb(meta),  # Store as JSONB
    ]

    # Vector metadata for vector store
    vector_metadata = {
        "timestamp": timestamp,
        "source": source,
        "categories": categories,
        "tags": tags,
    }

    return event_id, values, embed_vector, vector_metadata


def insert_news_events_batch(events_data: List[Tuple]) -> int:
    """
    Batch insert news events into database and vector store.

    Args:
        events_data: List of (event_id, values, vector, metadata) tuples

    Returns:
        Number of successfully inserted events
    """
    if not events_data:
        return 0

    cols = [
        "id",
        "timestamp",
        "source",
        "url",
        "title",
        "summary",
        "raw_text",
        "clean_text",
        "categories",
        "tags",
        "embed",
        "meta",
    ]

    from psycopg import sql
    from vector_store import get_vector_store

    # Step 1: Insert metadata into PostgreSQL
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = sql.SQL("INSERT INTO events ({}) VALUES ({})").format(
                sql.SQL(", ").join(sql.Identifier(col) for col in cols),
                sql.SQL(", ").join(sql.Placeholder() * len(cols)),
            )

            try:
                # Batch insert all at once
                cur.executemany(query, [values for _, values, _, _ in events_data])
                inserted = len(events_data)
                print(f"[sportsdata] ✓ Batch inserted {inserted} events to PostgreSQL")
            except Exception as e:
                print(f"[sportsdata] ✗ Batch insert failed: {e}")
                # Fallback to individual inserts
                for event_id, values, _, _ in events_data:
                    try:
                        cur.execute(query, values)
                        inserted += 1
                    except Exception as inner_e:
                        print(f"[sportsdata] ✗ Failed to insert {event_id}: {inner_e}")

    # Step 2: Insert vectors into vector store
    try:
        vector_store = get_vector_store()
        vectors = [
            (event_id, vector, metadata)
            for event_id, _, vector, metadata in events_data
        ]
        vector_store.insert_batch(vectors)
    except Exception as e:
        print(f"[sportsdata] ⚠️  Vector store insertion failed: {e}")
        # Continue anyway - vectors can be backfilled later

    return inserted


def backfill_news_events(
    teams: List[str],
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    filter_categories: Optional[List[str]] = None,
) -> Tuple[int, int]:
    """
    Backfill news events for teams from SportsData.io.

    Args:
        teams: List of team abbreviations (e.g., ["DAL", "KC"])
        start_date: Start date for backfill (defaults to NFL_EVENT_BACKFILL_START)
        end_date: End date for backfill (defaults to today)
        filter_categories: Optional categories to filter (e.g., ["Injuries"])

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    print(f"\n{'='*60}")
    print(f"[sportsdata] Backfilling news events for {', '.join(teams)}")
    print(f"{'='*60}")

    # Parse dates
    if start_date is None:
        from config import NFL_EVENT_BACKFILL_START
        start_date = parse_date(NFL_EVENT_BACKFILL_START)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)

    if end_date is None:
        end_date = datetime.now(timezone.utc)

    print(f"[sportsdata] Date range: {start_date.date()} to {end_date.date()}")
    if filter_categories:
        print(f"[sportsdata] Filtering categories: {filter_categories}")

    # Create API client
    try:
        client = SportsDataClient()
    except ValueError as e:
        print(f"[sportsdata] ✗ Configuration error: {e}")
        print("\nPlease set SPORTSDATA_API_KEY in backend/.env:")
        print("  SPORTSDATA_API_KEY=your-api-key-here")
        return 0, 0

    # Fetch news by date range
    news_items = fetch_news_by_date_range(
        client,
        start_date,
        end_date,
        team_filter=teams,
        filter_categories=filter_categories,
    )

    if not news_items:
        print(f"[sportsdata] No news items found")
        return 0, 0

    # Batch check existing NewsIDs
    news_ids = [item.get("NewsID") for item in news_items if item.get("NewsID")]
    existing_ids = get_existing_news_ids(news_ids)
    print(f"[sportsdata] Found {len(existing_ids)} existing NewsIDs in database")

    # Prepare events for insertion
    events_to_insert = []
    skipped = 0

    for item in news_items:
        news_id = item.get("NewsID")
        team_abbr = item.get("Team", "")

        # Skip if already exists
        if news_id and news_id in existing_ids:
            skipped += 1
            continue

        try:
            event_data = prepare_news_event(item, team_abbr)
            events_to_insert.append(event_data)
        except Exception as e:
            print(f"[sportsdata] ✗ Error preparing NewsID {news_id}: {e}")
            skipped += 1

    # Batch insert
    inserted = insert_news_events_batch(events_to_insert)

    print(f"\n[sportsdata] Backfill Results:")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped:  {skipped} (duplicates/errors)")

    return inserted, skipped


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: Game-Event Alignment Validation
# ═══════════════════════════════════════════════════════════════════════

def validate_event_coverage(
    team_symbols: Optional[List[str]] = None,
    lookback_days: int = 365,
    max_days_before_game: int = 7,
) -> Dict:
    """
    Validate event coverage for games.

    Analyzes how many events are associated with each game to determine
    if we have sufficient data for event-conditioned forecasting.

    Args:
        team_symbols: List of team symbols (defaults to all configured teams)
        lookback_days: How far back to analyze games
        max_days_before_game: Max days before game to count events

    Returns:
        Dictionary with coverage statistics
    """
    if team_symbols is None:
        team_symbols = list(TEAM_ABBR_TO_SYMBOL.values())

    print(f"\n{'='*60}")
    print(f"[sportsdata] Game-Event Coverage Validation")
    print(f"{'='*60}")
    print(f"Teams: {', '.join([s.split(':')[1] for s in team_symbols])}")
    print(f"Lookback: {lookback_days} days")
    print(f"Event window: {max_days_before_game} days before each game")
    print(f"{'='*60}\n")

    total_games = 0
    coverage_buckets = {
        "0": 0,      # No events
        "1-2": 0,    # Few events
        "3-5": 0,    # Moderate events
        "5+": 0,     # Many events
    }
    total_events = 0

    for team_symbol in team_symbols:
        team_abbr = team_symbol.split(":")[1].split("_")[0]
        print(f"\n[sportsdata] Analyzing {team_abbr}...")

        # Get historical game-event associations
        game_events = get_historical_events_for_games(
            team_symbol,
            lookback_days=lookback_days,
            max_days_before_game=max_days_before_game,
        )

        team_games = len(game_events)
        total_games += team_games

        print(f"  Found {team_games} games with event data")

        for game in game_events:
            event_count = game["events_count"]
            total_events += event_count

            # Categorize by coverage
            if event_count == 0:
                coverage_buckets["0"] += 1
            elif event_count <= 2:
                coverage_buckets["1-2"] += 1
            elif event_count <= 5:
                coverage_buckets["3-5"] += 1
            else:
                coverage_buckets["5+"] += 1

    # Calculate percentages
    print(f"\n{'='*60}")
    print(f"[sportsdata] Game Coverage Report")
    print(f"{'='*60}")
    print(f"Total games analyzed: {total_games}")

    if total_games > 0:
        for bucket, count in coverage_buckets.items():
            pct = (count / total_games) * 100
            print(f"  {bucket} events: {count} games ({pct:.1f}%)")

        avg_events = total_events / total_games if total_games > 0 else 0
        print(f"\nTotal events found: {total_events}")
        print(f"Average events/game: {avg_events:.1f}")
    else:
        print("  No games found in database!")

    print(f"{'='*60}\n")

    return {
        "total_games": total_games,
        "total_events": total_events,
        "avg_events_per_game": total_events / total_games if total_games > 0 else 0,
        "coverage_buckets": coverage_buckets,
    }


# ═══════════════════════════════════════════════════════════════════════
# Phase 3: Event Enrichment (Optional)
# ═══════════════════════════════════════════════════════════════════════

def enrich_with_injury_reports(
    team_abbr: str,
    season: int,
    weeks: List[int],
) -> Tuple[int, int]:
    """
    Enrich event data with structured injury reports.

    Uses the Injuries endpoint to create events from DeclaredInactive players.
    Only use this if news coverage is sparse.

    Args:
        team_abbr: Team abbreviation
        season: Season year
        weeks: List of week numbers to fetch

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    print(f"\n[sportsdata] Enriching with injury reports for {team_abbr}...")
    print(f"  Season: {season}, Weeks: {weeks}")

    try:
        client = SportsDataClient()
    except ValueError as e:
        print(f"[sportsdata] ✗ Configuration error: {e}")
        return 0, 0

    inserted = 0
    skipped = 0

    for week in weeks:
        try:
            injuries = client.get_injuries_by_team(season, week, team_abbr)

            for injury in injuries:
                # Only create events for declared inactive (definitive signal)
                if not injury.get("DeclaredInactive"):
                    continue

                # Create event text
                player_name = injury.get("Name", "Unknown")
                position = injury.get("Position", "")
                number = injury.get("Number", "")
                opponent = injury.get("Opponent", "")

                title = f"{player_name} ({position} #{number}) declared inactive vs {opponent}"
                content = f"Official injury report: {player_name} will not play in Week {week} vs {opponent}."

                # TODO: Convert to event structure and insert
                # This is optional enrichment - implement if needed

                print(f"  - {title}")

        except Exception as e:
            print(f"[sportsdata] ⚠️  Error fetching injuries for week {week}: {e}")

    return inserted, skipped


# ═══════════════════════════════════════════════════════════════════════
# Main CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    """Main entry point for CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill NFL news events from SportsData.io"
    )
    parser.add_argument(
        "--teams",
        nargs="+",
        default=DEFAULT_TEAMS,
        help=f"Team abbreviations to backfill (default: {' '.join(DEFAULT_TEAMS)})",
    )
    parser.add_argument(
        "--all-teams",
        action="store_true",
        help="Backfill all configured teams",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help=f"Start date for backfill (default: {NFL_EVENT_BACKFILL_START})",
    )
    parser.add_argument(
        "--filter-injuries",
        action="store_true",
        default=False,
        help="Only fetch injury-related news (default: False - fetch all categories)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only run validation report (skip ingestion)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=365,
        help="Days to look back for validation (default: 365)",
    )

    args = parser.parse_args()

    # Parse start date
    start_date = None
    if args.start_date:
        start_date = parse_date(args.start_date)
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)

    # Determine teams
    if args.all_teams:
        teams = list(TEAM_ABBR_TO_SYMBOL.keys())
    else:
        teams = args.teams

    # Validate-only mode
    if args.validate_only:
        team_symbols = [TEAM_ABBR_TO_SYMBOL[t] for t in teams if t in TEAM_ABBR_TO_SYMBOL]
        validate_event_coverage(team_symbols, lookback_days=args.lookback_days)
        return

    # Phase 1: Backfill news events
    print(f"\n{'='*60}")
    print(f"[sportsdata] Starting NFL News Event Backfill")
    print(f"{'='*60}")
    print(f"Teams: {', '.join(teams)}")
    print(f"Filter injuries: {args.filter_injuries}")
    print(f"{'='*60}\n")

    # Validate teams
    valid_teams = [t for t in teams if t in TEAM_ABBR_TO_SYMBOL]
    invalid_teams = [t for t in teams if t not in TEAM_ABBR_TO_SYMBOL]

    if invalid_teams:
        print(f"[sportsdata] ⚠️  Unknown teams (skipping): {', '.join(invalid_teams)}")

    if not valid_teams:
        print(f"[sportsdata] ✗ No valid teams specified")
        return

    filter_categories = ["Injuries"] if args.filter_injuries else None

    total_inserted, total_skipped = backfill_news_events(
        valid_teams,
        start_date=start_date,
        filter_categories=filter_categories,
    )

    # Summary
    print(f"\n{'='*60}")
    print(f"[sportsdata] Backfill Complete!")
    print(f"{'='*60}")
    print(f"Total inserted: {total_inserted} events")
    print(f"Total skipped:  {total_skipped} (duplicates/errors)")
    print(f"{'='*60}\n")

    # Phase 2: Validation report
    print("\n[sportsdata] Running validation report...\n")
    team_symbols = [TEAM_ABBR_TO_SYMBOL[t] for t in teams if t in TEAM_ABBR_TO_SYMBOL]
    validate_event_coverage(team_symbols, lookback_days=args.lookback_days)


if __name__ == "__main__":
    main()
