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
    tags TEXT[],                     -- ['btc','eth','exchange','sec']
    meta JSONB                       -- Additional metadata (news_id, player_id, etc.)
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

-- Projections: external model projections (e.g., NFL win probabilities)
-- Primary key supports multiple models and horizons for the same symbol/time
CREATE TABLE projections (
    symbol TEXT NOT NULL,                 -- 'NFL:DAL_COWBOYS', 'NFL:KC_CHIEFS', etc.
    as_of TIMESTAMPTZ NOT NULL,          -- When this projection was made
    horizon_minutes INT NOT NULL,         -- Forecast horizon in minutes
    metric TEXT NOT NULL,                 -- 'win_prob', 'spread', 'total', etc.
    projected_value DOUBLE PRECISION NOT NULL,  -- The projected value
    model_source TEXT NOT NULL,           -- 'baker_v2', 'fivethirtyeight', etc.
    game_id INT,                          -- External game identifier (nullable for non-game projections)
    run_id TEXT,                          -- Ingestion run identifier (for tracking)
    opponent TEXT,                        -- Opponent identifier (nullable)
    opponent_name TEXT,                   -- Human-readable opponent name
    meta JSONB,                           -- Additional metadata (home/away, spread, etc.)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT projections_pkey PRIMARY KEY (symbol, as_of, horizon_minutes, metric, model_source)
);

-- Indexes for efficient queries
CREATE INDEX idx_projections_symbol_metric_asof ON projections (symbol, metric, as_of DESC);
CREATE INDEX idx_projections_game ON projections (game_id, as_of DESC) WHERE game_id IS NOT NULL;

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

-- Metadata (GIN for JSONB queries)
CREATE INDEX idx_events_meta
ON events USING GIN (meta);

-- Forecast snapshots: time-series storage of forecast values for timeline graphs
-- Stores historical predictions to visualize how forecasts change over time as new events occur
-- Example: "3 days ago: 65% win prob → after QB injury: 52% → now: 58%"
CREATE TABLE forecast_snapshots (
    id SERIAL PRIMARY KEY,

    -- What is being forecasted
    symbol VARCHAR(50) NOT NULL,             -- 'NFL:DAL_COWBOYS', 'BTC-USD', etc.
    forecast_type VARCHAR(50) NOT NULL,      -- 'win_probability', 'price_return', 'point_spread'

    -- When this forecast was made
    snapshot_at TIMESTAMPTZ NOT NULL,        -- When this forecast snapshot was taken

    -- The forecast value
    forecast_value DOUBLE PRECISION NOT NULL, -- Win probability (0.0-1.0), return %, spread, etc.
    confidence DOUBLE PRECISION,              -- Confidence score (0.0-1.0), nullable
    sample_size INTEGER,                      -- Number of similar events/games used, nullable

    -- Forecast source and version
    model_source VARCHAR(50) NOT NULL,       -- 'ml_model_v2', 'baker_api', 'event_weighted', 'naive_baseline'
    model_version VARCHAR(20),               -- 'v2.0', 'v2.1', etc. (nullable for external sources)

    -- Optional event attribution (what triggered this snapshot?)
    event_id UUID REFERENCES events(id) ON DELETE SET NULL,  -- Triggering event (nullable)
    event_summary TEXT,                      -- Brief event description for UI tooltips

    -- Target prediction metadata
    target_date TIMESTAMPTZ,                 -- When the forecasted event will occur (e.g., game date)
    horizon_minutes INTEGER,                 -- Forecast horizon in minutes (nullable for non-time-based)

    -- Model metadata (flexible JSON for features, hyperparams, etc.)
    metadata JSONB,                          -- {features_used: [...], feature_version: "v1.0", training_date: "2025-12-01"}

    -- Audit trail
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevent exact duplicates (same symbol + type + source + time)
    -- Allows multiple snapshots at the same timestamp from different sources
    CONSTRAINT forecast_snapshots_unique UNIQUE(symbol, forecast_type, model_source, snapshot_at)
);

-- Timeline queries: Get forecast evolution for a symbol over date range
-- Query: WHERE symbol = 'NFL:DAL_COWBOYS' AND forecast_type = 'win_probability'
--        AND snapshot_at BETWEEN '2025-12-01' AND '2025-12-11' ORDER BY snapshot_at DESC
CREATE INDEX idx_forecast_snapshots_timeline ON forecast_snapshots (symbol, forecast_type, snapshot_at DESC);

-- Compare models: Get all forecast sources at specific time (A/B testing)
-- Query: WHERE symbol = 'NFL:DAL_COWBOYS' AND snapshot_at = '2025-12-10 14:00:00+00'
CREATE INDEX idx_forecast_snapshots_compare ON forecast_snapshots (symbol, snapshot_at DESC, model_source);

-- Event attribution: Find forecasts influenced by specific event
-- Query: WHERE event_id = '123e4567-e89b-12d3-a456-426614174000'
CREATE INDEX idx_forecast_snapshots_event ON forecast_snapshots (event_id) WHERE event_id IS NOT NULL;

-- Recent snapshots: Dashboard queries across all symbols
-- Query: SELECT DISTINCT ON (symbol, forecast_type, model_source) * ORDER BY snapshot_at DESC
CREATE INDEX idx_forecast_snapshots_recent ON forecast_snapshots (snapshot_at DESC);

-- Target date: Forecasts for upcoming games/events
-- Query: WHERE target_date BETWEEN NOW() AND NOW() + INTERVAL '7 days'
CREATE INDEX idx_forecast_snapshots_target ON forecast_snapshots (target_date) WHERE target_date IS NOT NULL;

-- Model versioning: A/B testing and performance comparison
-- Query: WHERE model_source = 'ml_model_v2' AND model_version = 'v2.0'
CREATE INDEX idx_forecast_snapshots_model ON forecast_snapshots (model_source, model_version) WHERE model_version IS NOT NULL;

-- Metadata queries: Feature version and model configuration
-- Query: WHERE metadata->>'feature_version' = 'v1.0'
CREATE INDEX idx_forecast_snapshots_metadata ON forecast_snapshots USING GIN (metadata);

-- Note: pgvector indexes (IVFFlat, HNSW) have a 2000 dimension limit.
-- For 3072-dim vectors, we skip the index and rely on exact search.
-- This is fine for < 100k events. For larger scale, consider dimensionality reduction.
