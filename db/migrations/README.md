# Migrations

## Available Migrations

- `001_ingest_status.sql`: adds ingest_status table for job heartbeats and the asset_projections index on (symbol, metric, as_of DESC).

- `001_nfl_structured_tables.sql`: adds NFL structured forecasting tables (team_stats, game_features, injuries) for ML-based predictions.

- `002_forecast_snapshots.sql`: DEPRECATED - table now in init.sql. Use `002_enhance_forecast_snapshots.sql` for existing databases.

- `002_enhance_forecast_snapshots.sql`: upgrades existing forecast_snapshots table to production-ready schema with model versioning, event attribution, and timeline support.

## How to Apply Migrations

### For Fresh Databases
Just use `db/init.sql` - it includes all tables including the latest forecast_snapshots schema.

```bash
# Run via docker-compose (recommended)
docker compose down -v && docker compose up -d db

# Or manually
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets -f db/init.sql
```

### For Existing Databases

Apply migrations in order:

```bash
# Navigate to project root
cd /path/to/bloombergGPT

# Apply specific migration
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets -f db/migrations/001_nfl_structured_tables.sql

# Enhance forecast_snapshots (if table already exists with old schema)
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets -f db/migrations/002_enhance_forecast_snapshots.sql
```

### Checking Migration Status

```bash
# Check if forecast_snapshots has new schema
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets -c "\d forecast_snapshots"

# Count rows in backup table (after migration)
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets -c "SELECT COUNT(*) FROM forecast_snapshots_old;"
```

## Rollback Procedures

Each migration includes rollback instructions in comments. Generally:

```sql
-- Rollback NFL structured tables
DROP TABLE IF EXISTS injuries CASCADE;
DROP TABLE IF EXISTS game_features CASCADE;
DROP TABLE IF EXISTS team_stats CASCADE;

-- Rollback forecast_snapshots enhancement
DROP TABLE IF EXISTS forecast_snapshots CASCADE;
ALTER TABLE forecast_snapshots_old RENAME TO forecast_snapshots;
```
