#!/usr/bin/env python3
"""
NFL Structured Tables Migration Script

This script applies the database migration for NFL structured forecasting tables.
It is idempotent and safe to run multiple times.

Usage:
    python -m migrate_nfl_tables           # Apply migration
    python -m migrate_nfl_tables --verify  # Verify migration without applying
    python -m migrate_nfl_tables --rollback # Rollback migration (DESTRUCTIVE!)

IMPORTANT: This migration is non-destructive. It does not modify existing tables.
The old event-based NFL forecasting system will continue to work.
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

from db import get_conn


def read_migration_sql() -> str:
    """Read the migration SQL file"""
    migration_file = Path(__file__).parent.parent / "db" / "migrations" / "001_nfl_structured_tables.sql"

    if not migration_file.exists():
        raise FileNotFoundError(f"Migration file not found: {migration_file}")

    with open(migration_file, "r") as f:
        return f.read()


def check_tables_exist() -> dict:
    """Check which tables already exist"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('team_stats', 'game_features', 'injuries')
            """)
            existing_tables = {row["table_name"] for row in cur.fetchall()}

    return {
        "team_stats": "team_stats" in existing_tables,
        "game_features": "game_features" in existing_tables,
        "injuries": "injuries" in existing_tables,
    }


def verify_migration() -> bool:
    """Verify the migration without applying it"""
    print("\n" + "=" * 60)
    print("MIGRATION VERIFICATION")
    print("=" * 60)

    # Check existing tables
    existing = check_tables_exist()

    print("\nTable Status:")
    for table_name, exists in existing.items():
        status = "EXISTS" if exists else "MISSING"
        symbol = "✓" if exists else "✗"
        print(f"  {symbol} {table_name}: {status}")

    # Check if migration is needed
    if all(existing.values()):
        print("\n✓ All tables already exist. Migration not needed.")
        return True
    else:
        missing_tables = [name for name, exists in existing.items() if not exists]
        print(f"\n⚠ Migration needed. Missing tables: {', '.join(missing_tables)}")
        return False


def apply_migration() -> None:
    """Apply the migration"""
    print("\n" + "=" * 60)
    print("APPLYING NFL STRUCTURED TABLES MIGRATION")
    print("=" * 60)

    # Check current state
    existing = check_tables_exist()

    if all(existing.values()):
        print("\n✓ All tables already exist. Nothing to do.")
        return

    # Read migration SQL
    print("\n[1/3] Reading migration SQL...")
    migration_sql = read_migration_sql()
    print("✓ Migration SQL loaded")

    # Apply migration
    print("\n[2/3] Applying migration...")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Execute migration (uses CREATE TABLE IF NOT EXISTS)
                cur.execute(migration_sql)
                conn.commit()
        print("✓ Migration applied successfully")
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        raise

    # Verify migration
    print("\n[3/3] Verifying migration...")
    existing_after = check_tables_exist()

    all_created = all(existing_after.values())
    if all_created:
        print("✓ All tables created successfully")
    else:
        missing = [name for name, exists in existing_after.items() if not exists]
        print(f"✗ Migration incomplete. Missing tables: {', '.join(missing)}")
        sys.exit(1)

    # Count rows in new tables
    print("\nTable Status:")
    with get_conn() as conn:
        with conn.cursor() as cur:
            for table_name in ["team_stats", "game_features", "injuries"]:
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cur.fetchone()["count"]
                print(f"  ✓ {table_name}: {count} rows")

    print("\n" + "=" * 60)
    print("✓ MIGRATION COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run backfill script: python -m ingest.backfill_team_stats")
    print("  2. Build game features: python -m signals.game_feature_builder")
    print("  3. Train ML model: python -m notebooks.nfl_xgboost_training")
    print()


def rollback_migration() -> None:
    """Rollback the migration (DESTRUCTIVE!)"""
    print("\n" + "=" * 60)
    print("WARNING: ROLLBACK MIGRATION")
    print("=" * 60)
    print("\nThis will DELETE the following tables and ALL their data:")
    print("  - team_stats")
    print("  - game_features")
    print("  - injuries")
    print("\nThis action is IRREVERSIBLE!")
    print("=" * 60)

    # Require explicit confirmation
    confirmation = input("\nType 'DELETE ALL DATA' to confirm rollback: ")

    if confirmation != "DELETE ALL DATA":
        print("\n✗ Rollback cancelled. No changes made.")
        return

    print("\nRolling back migration...")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Drop tables in reverse dependency order
                cur.execute("DROP TABLE IF EXISTS injuries CASCADE")
                cur.execute("DROP TABLE IF EXISTS game_features CASCADE")
                cur.execute("DROP TABLE IF EXISTS team_stats CASCADE")
                conn.commit()

        print("✓ Rollback complete. All tables dropped.")
    except Exception as e:
        print(f"✗ Rollback failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="NFL Structured Tables Migration")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--verify",
        action="store_true",
        help="Verify migration status without applying"
    )
    group.add_argument(
        "--rollback",
        action="store_true",
        help="Rollback migration (DESTRUCTIVE!)"
    )

    args = parser.parse_args()

    if args.verify:
        verify_migration()
    elif args.rollback:
        rollback_migration()
    else:
        apply_migration()


if __name__ == "__main__":
    main()
