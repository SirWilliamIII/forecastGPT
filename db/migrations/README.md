# Migrations

- `001_ingest_status.sql`: adds ingest_status table for job heartbeats and the asset_projections index on (symbol, metric, as_of DESC).

Apply with:
```bash
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets -f db/migrations/001_ingest_status.sql
```
