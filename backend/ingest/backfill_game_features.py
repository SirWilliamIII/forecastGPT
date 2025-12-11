# backend/ingest/backfill_game_features.py
"""
Backfill script for NFL game features.

Loads historical games from asset_returns and team_stats, computes ML features,
and populates the game_features table for model training.

Usage:
    python -m ingest.backfill_game_features
"""

import sys
from datetime import datetime, timezone

from signals.game_feature_builder import backfill_game_features
from db import get_conn


def validate_features() -> None:
    """
    Validate feature completeness and quality after backfill.

    Checks:
    - No NaN values in critical features
    - Feature ranges (e.g., win_pct in [0, 1])
    - Data quality warnings
    """
    print("\n" + "=" * 60)
    print("VALIDATING FEATURE QUALITY")
    print("=" * 60)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get total count
            cur.execute("SELECT COUNT(*) as total FROM game_features")
            total = cur.fetchone()["total"]
            print(f"\nTotal games in game_features: {total}")

            if total == 0:
                print("✗ No games found. Run backfill first.")
                return

            # Check for NULL values in critical features
            critical_features = [
                "home_win_pct", "away_win_pct",
                "home_points_avg", "away_points_avg",
                "home_point_diff_avg", "away_point_diff_avg",
            ]

            print("\nChecking for NULL values in critical features:")
            for feature in critical_features:
                cur.execute(f"SELECT COUNT(*) as null_count FROM game_features WHERE {feature} IS NULL")
                null_count = cur.fetchone()["null_count"]
                pct = (null_count / total) * 100 if total > 0 else 0
                status = "✓" if null_count == 0 else "⚠"
                print(f"  {status} {feature}: {null_count}/{total} NULL ({pct:.1f}%)")

            # Check feature ranges
            print("\nChecking feature ranges:")

            # Win percentages should be in [0, 1]
            cur.execute("""
                SELECT COUNT(*) as invalid
                FROM game_features
                WHERE home_win_pct < 0 OR home_win_pct > 1
                   OR away_win_pct < 0 OR away_win_pct > 1
            """)
            invalid_win_pct = cur.fetchone()["invalid"]
            status = "✓" if invalid_win_pct == 0 else "✗"
            print(f"  {status} Win percentages in [0,1]: {total - invalid_win_pct}/{total} valid")

            # Points should be positive
            cur.execute("""
                SELECT COUNT(*) as invalid
                FROM game_features
                WHERE home_points_avg < 0 OR away_points_avg < 0
            """)
            invalid_points = cur.fetchone()["invalid"]
            status = "✓" if invalid_points == 0 else "✗"
            print(f"  {status} Points averages ≥ 0: {total - invalid_points}/{total} valid")

            # Check outcome labels (for completed games)
            cur.execute("""
                SELECT
                    COUNT(*) as games_with_outcomes,
                    SUM(CASE WHEN home_win THEN 1 ELSE 0 END) as home_wins,
                    SUM(CASE WHEN NOT home_win THEN 1 ELSE 0 END) as away_wins
                FROM game_features
                WHERE home_score IS NOT NULL AND away_score IS NOT NULL
            """)
            outcomes = cur.fetchone()
            print(f"\nOutcome labels:")
            print(f"  Games with scores: {outcomes['games_with_outcomes']}/{total}")
            if outcomes["games_with_outcomes"] > 0:
                home_win_pct = (outcomes["home_wins"] / outcomes["games_with_outcomes"]) * 100
                print(f"  Home wins: {outcomes['home_wins']} ({home_win_pct:.1f}%)")
                print(f"  Away wins: {outcomes['away_wins']} ({100-home_win_pct:.1f}%)")

            # Baker projections coverage
            cur.execute("SELECT COUNT(*) as with_baker FROM game_features WHERE baker_home_win_prob IS NOT NULL")
            with_baker = cur.fetchone()["with_baker"]
            baker_pct = (with_baker / total) * 100 if total > 0 else 0
            print(f"\nExternal signals:")
            print(f"  Baker projections: {with_baker}/{total} games ({baker_pct:.1f}%)")

            # Feature version consistency
            cur.execute("SELECT features_version, COUNT(*) as count FROM game_features GROUP BY features_version")
            versions = cur.fetchall()
            print(f"\nFeature versions:")
            for v in versions:
                print(f"  {v['features_version']}: {v['count']} games")

            # Summary statistics for key features
            print("\nFeature statistics:")
            cur.execute("""
                SELECT
                    AVG(home_win_pct) as avg_home_win_pct,
                    AVG(away_win_pct) as avg_away_win_pct,
                    AVG(home_points_avg) as avg_home_pts,
                    AVG(away_points_avg) as avg_away_pts,
                    AVG(home_point_diff_avg) as avg_home_diff,
                    AVG(away_point_diff_avg) as avg_away_diff
                FROM game_features
                WHERE home_win_pct IS NOT NULL
            """)
            stats = cur.fetchone()
            if stats:
                # Print each stat with NULL handling
                def fmt(val, fmt_str):
                    return fmt_str.format(val) if val is not None else "N/A"

                print(f"  Avg home win%: {fmt(stats['avg_home_win_pct'], '{:.3f}')}")
                print(f"  Avg away win%: {fmt(stats['avg_away_win_pct'], '{:.3f}')}")
                print(f"  Avg home pts/game: {fmt(stats['avg_home_pts'], '{:.1f}')}")
                print(f"  Avg away pts/game: {fmt(stats['avg_away_pts'], '{:.1f}')}")
                print(f"  Avg home pt diff: {fmt(stats['avg_home_diff'], '{:.1f}')}")
                print(f"  Avg away pt diff: {fmt(stats['avg_away_diff'], '{:.1f}')}")
            else:
                print(f"  No games with features computed")


def print_sample_features(limit: int = 3) -> None:
    """Print sample feature rows for inspection."""
    print("\n" + "=" * 60)
    print("SAMPLE FEATURE ROWS")
    print("=" * 60)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    game_id,
                    home_team,
                    away_team,
                    game_date,
                    home_win_pct,
                    away_win_pct,
                    home_points_avg,
                    away_points_avg,
                    home_score,
                    away_score,
                    home_win,
                    baker_home_win_prob
                FROM game_features
                ORDER BY game_date DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

            for i, row in enumerate(rows, 1):
                print(f"\nGame {i}: {row['game_id']}")
                print(f"  Date: {row['game_date'].date()}")
                print(f"  Matchup: {row['home_team']} vs {row['away_team']}")
                print(f"  Home features: win%={row['home_win_pct']:.3f}, pts/g={row['home_points_avg']:.1f}")
                print(f"  Away features: win%={row['away_win_pct']:.3f}, pts/g={row['away_points_avg']:.1f}")
                if row['home_score'] is not None:
                    outcome = "HOME WIN" if row['home_win'] else "AWAY WIN"
                    print(f"  Outcome: {row['home_score']}-{row['away_score']} ({outcome})")
                if row['baker_home_win_prob'] is not None:
                    print(f"  Baker projection: {row['baker_home_win_prob']:.3f}")


def main():
    """Main backfill execution."""
    print("=" * 60)
    print("NFL GAME FEATURES BACKFILL")
    print("=" * 60)

    # Define teams to backfill
    teams = [
        "NFL:DAL_COWBOYS",
        "NFL:KC_CHIEFS",
    ]

    print(f"\nTeams to process: {', '.join(teams)}")
    print(f"Seasons: 2023-2025")
    print(f"\nStarting backfill at {datetime.now(tz=timezone.utc).isoformat()}\n")

    # Run backfill
    try:
        inserted, updated, skipped = backfill_game_features(
            team_symbols=teams,
            start_season=2023,
            end_season=2025,
        )

        print("\n" + "=" * 60)
        print("BACKFILL COMPLETE")
        print("=" * 60)
        print(f"\nResults:")
        print(f"  ✓ Inserted: {inserted} games")
        print(f"  ✓ Updated: {updated} games")
        print(f"  ⚠ Skipped: {skipped} games")
        print(f"  Total processed: {inserted + updated + skipped} games")

        # Validate features
        validate_features()

        # Print samples
        print_sample_features(limit=3)

        print("\n" + "=" * 60)
        print("✓ Backfill completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Backfill failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
