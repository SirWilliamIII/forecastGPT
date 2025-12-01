-- Migration: Add feed_metadata table for RSS ingestion optimization
-- Date: 2025-12-01
-- Description: Tracks last fetch time per RSS source to enable timestamp filtering

-- Create feed_metadata table
CREATE TABLE IF NOT EXISTS feed_metadata (
    source TEXT PRIMARY KEY,
    last_fetched TIMESTAMPTZ NOT NULL,
    last_entry_count INT NOT NULL DEFAULT 0,
    last_inserted_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add helpful comment
COMMENT ON TABLE feed_metadata IS 'Tracks RSS feed ingestion history for optimization';
COMMENT ON COLUMN feed_metadata.source IS 'RSS source identifier (e.g., wired_ai)';
COMMENT ON COLUMN feed_metadata.last_fetched IS 'UTC timestamp of last successful fetch';
COMMENT ON COLUMN feed_metadata.last_entry_count IS 'Total entries found in last fetch';
COMMENT ON COLUMN feed_metadata.last_inserted_count IS 'New entries inserted in last fetch';
