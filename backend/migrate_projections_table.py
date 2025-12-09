#!/usr/bin/env python3
"""
Migration script: Rename asset_projections table to projections.

This script handles the table rename from 'asset_projections' to 'projections'
for better naming consistency and simplicity.

Usage:
    python -m migrate_projections_table [--dry-run] [--drop-old]

Options:
    --dry-run    Show what would be done without making changes
    --drop-old   Drop the old asset_projections table after migration (use with caution!)
"""

import sys
import argparse
from db import get_conn


def check_tables() -> tuple[bool, bool]:
    """
    Check which tables exist.

    Returns:
        (old_exists, new_exists) tuple
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Check for old table
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'asset_projections'
                ) as exists_check
            """)
            result = cur.fetchone()
            old_exists = result['exists_check'] if result else False

            # Check for new table
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'projections'
                ) as exists_check
            """)
            result = cur.fetchone()
            new_exists = result['exists_check'] if result else False

            return old_exists, new_exists


def count_rows(table_name: str) -> int:
    """Count rows in a table."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
            result = cur.fetchone()
            return result['cnt'] if result else 0


def migrate_data(dry_run: bool = False) -> None:
    """
    Migrate data from asset_projections to projections.

    Args:
        dry_run: If True, only show what would be done
    """
    old_exists, new_exists = check_tables()

    print("=" * 60)
    print("Migration Status Check")
    print("=" * 60)
    print(f"Old table (asset_projections) exists: {old_exists}")
    print(f"New table (projections) exists: {new_exists}")

    if not old_exists and new_exists:
        print("\n✓ Migration already complete!")
        print("  The 'projections' table exists and 'asset_projections' is gone.")
        return

    if not old_exists and not new_exists:
        print("\n⚠ Neither table exists!")
        print("  This is expected for a fresh database.")
        print("  Run db/init.sql to create the 'projections' table.")
        return

    # Count rows in old table
    old_count = count_rows("asset_projections") if old_exists else 0
    print(f"\nRows in asset_projections: {old_count}")

    if old_count == 0:
        print("\n⚠ Old table is empty. No data to migrate.")
        if new_exists:
            print("  The new 'projections' table already exists.")
            print("  You can safely drop the old table with --drop-old flag.")
        else:
            print("  Renaming empty table to 'projections'...")
            if not dry_run:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("ALTER TABLE asset_projections RENAME TO projections")
                        # Rename constraints
                        cur.execute("ALTER TABLE projections RENAME CONSTRAINT asset_projections_pkey TO projections_pkey")
                        # Rename indexes (only the one that exists)
                        cur.execute("ALTER INDEX idx_asset_projections_symbol_metric_asof RENAME TO idx_projections_symbol_metric_asof")
                print("  ✓ Table renamed successfully!")
            else:
                print("  [DRY RUN] Would rename asset_projections to projections")
        return

    # There's data to migrate
    print(f"\n📊 Found {old_count} rows to migrate")

    if new_exists:
        new_count = count_rows("projections")
        print(f"   New table already has {new_count} rows")

        if new_count > 0:
            print("\n⚠ WARNING: Both tables exist with data!")
            print("  This is an unexpected state. Manual intervention recommended.")
            print("  Options:")
            print("    1. If 'projections' has the correct data, use --drop-old to remove old table")
            print("    2. If 'asset_projections' has the correct data, drop 'projections' and re-run")
            print("    3. Manually reconcile the data")
            return

        # New table exists but is empty - copy data
        print("\n🔄 Migrating data from asset_projections to projections...")
        if not dry_run:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO projections
                        SELECT * FROM asset_projections
                        ON CONFLICT DO NOTHING
                    """)
                    inserted = cur.rowcount
            print(f"  ✓ Migrated {inserted} rows successfully!")

            # Verify
            new_count = count_rows("projections")
            print(f"  ✓ Verification: projections table now has {new_count} rows")
        else:
            print(f"  [DRY RUN] Would copy {old_count} rows to projections table")
    else:
        # New table doesn't exist - just rename
        print("\n🔄 Renaming asset_projections to projections...")
        if not dry_run:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("ALTER TABLE asset_projections RENAME TO projections")
                    # Rename constraints
                    cur.execute("ALTER TABLE projections RENAME CONSTRAINT asset_projections_pkey TO projections_pkey")
                    # Rename indexes (only the one that exists)
                    cur.execute("ALTER INDEX idx_asset_projections_symbol_metric_asof RENAME TO idx_projections_symbol_metric_asof")
            print("  ✓ Table renamed successfully!")
        else:
            print("  [DRY RUN] Would rename table and all associated constraints/indexes")


def drop_old_table(dry_run: bool = False) -> None:
    """Drop the old asset_projections table."""
    old_exists, new_exists = check_tables()

    if not old_exists:
        print("\n✓ Old table (asset_projections) doesn't exist. Nothing to drop.")
        return

    if not new_exists:
        print("\n⚠ WARNING: Cannot drop old table because new table doesn't exist!")
        print("  Run migration first before dropping the old table.")
        return

    old_count = count_rows("asset_projections")
    new_count = count_rows("projections")

    print(f"\n⚠ About to drop asset_projections table ({old_count} rows)")
    print(f"   New projections table has {new_count} rows")

    if old_count != new_count:
        print("\n⛔ ERROR: Row counts don't match!")
        print("   Refusing to drop old table. Please investigate the discrepancy.")
        return

    if not dry_run:
        confirm = input("\nType 'YES' to confirm deletion: ")
        if confirm != "YES":
            print("  ✗ Aborted.")
            return

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE asset_projections CASCADE")
        print("  ✓ Old table dropped successfully!")
    else:
        print("  [DRY RUN] Would drop asset_projections table")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate asset_projections table to projections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview what would happen
  python -m migrate_projections_table --dry-run

  # Run the migration
  python -m migrate_projections_table

  # Run migration and drop old table (after verifying)
  python -m migrate_projections_table --drop-old
        """
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--drop-old",
        action="store_true",
        help="Drop the old asset_projections table after successful migration"
    )

    args = parser.parse_args()

    try:
        print("\n🔧 Projections Table Migration Tool")
        print("=" * 60)

        if args.dry_run:
            print("🔍 DRY RUN MODE - No changes will be made")
            print("=" * 60)

        # Run migration
        migrate_data(dry_run=args.dry_run)

        # Optionally drop old table
        if args.drop_old:
            print("\n" + "=" * 60)
            drop_old_table(dry_run=args.dry_run)

        print("\n" + "=" * 60)
        print("✓ Migration tool completed")
        print("=" * 60)

    except Exception as e:
        print(f"\n⛔ ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
