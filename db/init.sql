-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Asset returns: realized returns for forecasting
CREATE TABLE asset_returns (
    symbol TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    horizon_minutes INT NOT NULL,
    realized_return DOUBLE PRECISION NOT NULL,
    price_start DOUBLE PRECISION NOT NULL,
    price_end DOUBLE PRECISION NOT NULL,
    CONSTRAINT asset_returns_pkey PRIMARY KEY (symbol, as_of, horizon_minutes)
);

CREATE INDEX idx_asset_returns_lookup
ON asset_returns (symbol, horizon_minutes, as_of);

-- Events: news / announcements / filings / tweets, etc.
CREATE TABLE events (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,            -- 'binance_announce', 'sec_rss', etc.
    url TEXT UNIQUE,                 -- canonicalized URL (unique to prevent duplicates)
    title TEXT,                      -- headline or title
    summary TEXT,                    -- short summary or description
    raw_text TEXT NOT NULL,
    clean_text TEXT,
    embed VECTOR(3072),              -- semantic fingerprint (text-embedding-3-large)
    categories TEXT[],               -- ['regulatory','hack','macro']
    tags TEXT[]                      -- ['btc','eth','exchange','sec']
);

-- Price history: stocks, crypto, indices, whatever
CREATE TABLE prices (
    asset TEXT NOT NULL,             -- 'BTC', 'ETH', 'SPY'
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    PRIMARY KEY (asset, timestamp)
);

-- Derived stats: what happened after each event for each asset
CREATE TABLE event_impacts (
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    asset TEXT NOT NULL,
    delta_1d NUMERIC,                -- % move 1 day after event
    delta_7d NUMERIC,                -- % move 7 days after
    delta_30d NUMERIC,               -- % move 30 days after
    max_drawdown NUMERIC,            -- worst drop in that window
    vol_change NUMERIC,              -- ratio vs baseline vol
    PRIMARY KEY (event_id, asset)
);

-- Feed metadata: track last fetch time per RSS source
CREATE TABLE feed_metadata (
    source TEXT PRIMARY KEY,
    last_fetched TIMESTAMPTZ NOT NULL,
    last_entry_count INT NOT NULL DEFAULT 0,
    last_inserted_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Helpful indexes

-- Fast time range queries on prices
CREATE INDEX idx_prices_asset_time
ON prices (asset, timestamp);

-- Quick filters on event time
CREATE INDEX idx_events_time
ON events (timestamp);

-- Tags & categories (GIN for arrays)
CREATE INDEX idx_events_categories
ON events USING GIN (categories);

CREATE INDEX idx_events_tags
ON events USING GIN (tags);

-- Note: pgvector indexes (IVFFlat, HNSW) have a 2000 dimension limit.
-- For 3072-dim vectors, we skip the index and rely on exact search.
-- This is fine for < 100k events. For larger scale, consider dimensionality reduction.
