-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Events: news / announcements / filings / tweets, etc.
CREATE TABLE events (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,            -- 'binance_announce', 'sec_rss', etc.
    url TEXT,
    raw_text TEXT NOT NULL,
    clean_text TEXT,
    embed VECTOR(1536),              -- semantic fingerprint
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

-- Vector index for semantic similarity
CREATE INDEX idx_events_embed
ON events
USING ivfflat (embed vector_l2_ops)
WITH (lists = 100);
