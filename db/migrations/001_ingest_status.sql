-- Migration: ingest_status tracking + projections index (idempotent)

CREATE TABLE IF NOT EXISTS ingest_status (
    job_name TEXT PRIMARY KEY,
    last_success TIMESTAMPTZ,
    last_error TIMESTAMPTZ,
    last_error_message TEXT,
    last_rows_inserted INT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_asset_projections_symbol_metric_asof
ON asset_projections (symbol, metric, as_of DESC);
