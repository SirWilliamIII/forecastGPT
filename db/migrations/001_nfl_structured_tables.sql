-- Migration: NFL Structured Forecasting Tables
-- Created: 2025-12-10
-- Purpose: Add structured data tables for statistical NFL forecasting
--
-- This migration adds three new tables to support machine learning-based
-- NFL game predictions using structured statistics instead of semantic events.
--
-- IMPORTANT: This is NON-DESTRUCTIVE. Existing tables (asset_returns, events)
-- are not modified. The old event-based NFL forecasting system will continue
-- to work during the migration period.

-- ═══════════════════════════════════════════════════════════════════════
-- Table 1: team_stats
-- Purpose: Store weekly team performance statistics from SportsData.io
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS team_stats (
    id SERIAL PRIMARY KEY,

    -- Team identification
    team_symbol VARCHAR(50) NOT NULL,        -- NFL:DAL_COWBOYS, etc.
    season INTEGER NOT NULL,                 -- 2024, 2025, etc.
    week INTEGER NOT NULL,                   -- 1-18 (regular), 19-22 (playoffs)

    -- Offensive statistics (cumulative season totals)
    points_scored FLOAT,                     -- Total points scored
    yards_total FLOAT,                       -- Total offensive yards
    yards_passing FLOAT,                     -- Passing yards
    yards_rushing FLOAT,                     -- Rushing yards
    turnovers INTEGER,                       -- Total turnovers (INT + fumbles lost)
    third_down_pct FLOAT,                    -- Third down conversion %
    red_zone_pct FLOAT,                      -- Red zone scoring %

    -- Defensive statistics (cumulative season totals)
    points_allowed FLOAT,                    -- Total points allowed
    yards_allowed FLOAT,                     -- Total yards allowed
    sacks INTEGER,                           -- Sacks recorded
    interceptions INTEGER,                   -- Interceptions
    fumbles_recovered INTEGER,               -- Fumbles recovered

    -- Derived metrics (computed fields)
    offensive_rank INTEGER,                  -- League offensive rank (1-32)
    defensive_rank INTEGER,                  -- League defensive rank (1-32)
    point_differential FLOAT,                -- points_scored - points_allowed
    win_count INTEGER,                       -- Wins this season
    loss_count INTEGER,                      -- Losses this season
    win_pct FLOAT,                           -- Win percentage (0.0 to 1.0)

    -- Metadata
    as_of TIMESTAMPTZ NOT NULL,              -- When this stat snapshot was taken
    source VARCHAR(50) DEFAULT 'sportsdata', -- Data source (sportsdata, espn, etc.)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Unique constraint: one stat row per team/season/week
    CONSTRAINT team_stats_unique UNIQUE(team_symbol, season, week)
);

-- Indexes for efficient queries
CREATE INDEX idx_team_stats_symbol_season ON team_stats(team_symbol, season DESC);
CREATE INDEX idx_team_stats_season_week ON team_stats(season, week);
CREATE INDEX idx_team_stats_as_of ON team_stats(as_of DESC);

-- ═══════════════════════════════════════════════════════════════════════
-- Table 2: game_features
-- Purpose: Pre-computed ML features for each game (both historical and upcoming)
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS game_features (
    id SERIAL PRIMARY KEY,

    -- Game identification
    game_id VARCHAR(100) UNIQUE NOT NULL,    -- Unique game identifier (from source)

    -- Game metadata
    home_team VARCHAR(50) NOT NULL,          -- NFL:DAL_COWBOYS
    away_team VARCHAR(50) NOT NULL,          -- NFL:NYG_GIANTS
    game_date TIMESTAMPTZ NOT NULL,          -- Scheduled game time
    season INTEGER NOT NULL,                 -- 2024, 2025, etc.
    week INTEGER NOT NULL,                   -- Week number
    is_playoff BOOLEAN DEFAULT FALSE,        -- Playoff game flag

    -- Pre-computed ML features (10-15 key features for simple model)
    -- Home team features
    home_win_pct FLOAT,                      -- Home team win % this season
    home_points_avg FLOAT,                   -- Avg points scored per game
    home_points_allowed_avg FLOAT,           -- Avg points allowed per game
    home_point_diff_avg FLOAT,               -- Avg point differential
    home_last3_win_pct FLOAT,                -- Win % in last 3 games
    home_offensive_rank INTEGER,             -- League offensive rank
    home_defensive_rank INTEGER,             -- League defensive rank

    -- Away team features
    away_win_pct FLOAT,                      -- Away team win % this season
    away_points_avg FLOAT,                   -- Avg points scored per game
    away_points_allowed_avg FLOAT,           -- Avg points allowed per game
    away_point_diff_avg FLOAT,               -- Avg point differential
    away_last3_win_pct FLOAT,                -- Win % in last 3 games
    away_offensive_rank INTEGER,             -- League offensive rank
    away_defensive_rank INTEGER,             -- League defensive rank

    -- Matchup features
    head_to_head_home_wins INTEGER,          -- Home team wins in H2H history
    head_to_head_away_wins INTEGER,          -- Away team wins in H2H history
    rest_days_home INTEGER,                  -- Days since home team's last game
    rest_days_away INTEGER,                  -- Days since away team's last game

    -- External signals (optional, can be NULL for historical games)
    baker_home_win_prob FLOAT,               -- Baker API home team win probability
    baker_spread FLOAT,                      -- Baker API point spread

    -- Actual outcomes (NULL for future games, filled after game completion)
    home_score INTEGER,                      -- Final home team score
    away_score INTEGER,                      -- Final away team score
    home_win BOOLEAN,                        -- True if home team won
    point_differential INTEGER,              -- home_score - away_score

    -- Metadata
    features_version VARCHAR(20) NOT NULL,   -- Feature schema version (e.g., "v1.0")
    computed_at TIMESTAMPTZ DEFAULT NOW(),   -- When features were computed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX idx_game_features_date ON game_features(game_date DESC);
CREATE INDEX idx_game_features_teams ON game_features(home_team, away_team);
CREATE INDEX idx_game_features_season_week ON game_features(season, week);
CREATE INDEX idx_game_features_outcome ON game_features(home_win) WHERE home_win IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════
-- Table 3: injuries (OPTIONAL - Simple MVP version)
-- Purpose: Track player injuries and their estimated impact on team performance
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS injuries (
    id SERIAL PRIMARY KEY,

    -- Team and player identification
    team_symbol VARCHAR(50) NOT NULL,        -- NFL:DAL_COWBOYS
    player_name VARCHAR(200) NOT NULL,       -- Player full name
    position VARCHAR(10),                    -- QB, RB, WR, etc.

    -- Injury details
    injury_status VARCHAR(50),               -- Out, Questionable, Doubtful, IR
    injury_description TEXT,                 -- Brief injury description

    -- Impact assessment (simple scoring: 0.0 = no impact, 1.0 = critical player)
    impact_score FLOAT DEFAULT 0.5,          -- Estimated impact on team (0.0 to 1.0)

    -- Temporal tracking
    reported_date TIMESTAMPTZ NOT NULL,      -- When injury was first reported
    expected_return_date TIMESTAMPTZ,        -- Expected return date (if known)
    game_date TIMESTAMPTZ,                   -- Next game this affects (nullable)

    -- Metadata
    source VARCHAR(50) DEFAULT 'sportsdata', -- Data source
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX idx_injuries_team_game ON injuries(team_symbol, game_date);
CREATE INDEX idx_injuries_status ON injuries(injury_status);
CREATE INDEX idx_injuries_reported ON injuries(reported_date DESC);

-- ═══════════════════════════════════════════════════════════════════════
-- Migration Notes
-- ═══════════════════════════════════════════════════════════════════════

-- This migration is designed to be:
-- 1. NON-DESTRUCTIVE: Does not modify existing tables
-- 2. IDEMPOTENT: Safe to run multiple times (IF NOT EXISTS checks)
-- 3. BACKWARD COMPATIBLE: Old event-based system continues to work
-- 4. REVERSIBLE: Can be rolled back by dropping these three tables

-- To roll back this migration:
-- DROP TABLE IF EXISTS injuries CASCADE;
-- DROP TABLE IF EXISTS game_features CASCADE;
-- DROP TABLE IF EXISTS team_stats CASCADE;

-- Feature versioning:
-- The features_version field in game_features tracks the feature schema.
-- When adding/removing features, increment the version (v1.0 -> v1.1).
-- This ensures ML models can validate they're using the correct feature set.

-- Data sources:
-- - team_stats: Primarily SportsData.io, fallback to ESPN API
-- - game_features: Computed from team_stats + external APIs
-- - injuries: SportsData.io injury reports (optional for MVP)

-- Dual-write strategy:
-- During migration, game outcomes will be written to BOTH:
-- 1. asset_returns (old system) - for continuity
-- 2. game_features (new system) - for ML training
-- After validation period, asset_returns writes can be deprecated.
