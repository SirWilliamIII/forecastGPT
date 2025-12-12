# backend/config.py
"""
Centralized configuration for the BloombergGPT backend.

All magic numbers, thresholds, and tunable parameters should be defined here
to improve maintainability and prevent scattered hardcoded values.
"""

import os
from typing import Dict, List

# ═══════════════════════════════════════════════════════════════════════
# Database Configuration
# ═══════════════════════════════════════════════════════════════════════

DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
DB_POOL_TIMEOUT = float(os.getenv("DB_POOL_TIMEOUT", "5.0"))

# ═══════════════════════════════════════════════════════════════════════
# Embeddings Configuration
# ═══════════════════════════════════════════════════════════════════════

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "3072"))
OPENAI_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
OPENAI_TIMEOUT = float(os.getenv("OPENAI_EMBED_TIMEOUT", "15.0"))
MAX_EMBED_RETRIES = int(os.getenv("MAX_EMBED_RETRIES", "3"))

# ═══════════════════════════════════════════════════════════════════════
# Forecasting Configuration
# ═══════════════════════════════════════════════════════════════════════

# Naive forecaster thresholds
FORECAST_DIRECTION_THRESHOLD = float(os.getenv("FORECAST_DIRECTION_THRESHOLD", "0.0005"))
FORECAST_CONFIDENCE_SCALE = float(os.getenv("FORECAST_CONFIDENCE_SCALE", "2.0"))

# Event forecaster parameters
EVENT_FORECAST_DEFAULT_K_NEIGHBORS = int(os.getenv("EVENT_FORECAST_K_NEIGHBORS", "25"))
EVENT_FORECAST_DEFAULT_ALPHA = float(os.getenv("EVENT_FORECAST_ALPHA", "0.5"))
EVENT_FORECAST_DEFAULT_LOOKBACK_DAYS = int(os.getenv("EVENT_FORECAST_LOOKBACK_DAYS", "365"))
EVENT_FORECAST_PRICE_WINDOW_MINUTES = int(os.getenv("EVENT_FORECAST_PRICE_WINDOW", "60"))

# Default horizons (in minutes)
DEFAULT_HORIZON_MINUTES = int(os.getenv("DEFAULT_HORIZON_MINUTES", "1440"))  # 24 hours
DEFAULT_LOOKBACK_DAYS = int(os.getenv("DEFAULT_LOOKBACK_DAYS", "60"))

# ═══════════════════════════════════════════════════════════════════════
# Ingestion Configuration
# ═══════════════════════════════════════════════════════════════════════

MAX_FETCH_RETRIES = int(os.getenv("MAX_FETCH_RETRIES", "3"))
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "10"))
MAX_DOWNLOAD_RETRIES = int(os.getenv("MAX_DOWNLOAD_RETRIES", "3"))

# Scheduler intervals (in hours)
RSS_INGEST_INTERVAL_HOURS = int(os.getenv("RSS_INGEST_INTERVAL_HOURS", "1"))
CRYPTO_BACKFILL_INTERVAL_HOURS = int(os.getenv("CRYPTO_BACKFILL_INTERVAL_HOURS", "24"))
EQUITY_BACKFILL_INTERVAL_HOURS = int(os.getenv("EQUITY_BACKFILL_INTERVAL_HOURS", "24"))
NFL_ELO_BACKFILL_INTERVAL_HOURS = int(os.getenv("NFL_ELO_BACKFILL_INTERVAL_HOURS", "24"))
BAKER_PROJECTIONS_INTERVAL_HOURS = int(os.getenv("BAKER_PROJECTIONS_INTERVAL_HOURS", "1"))
NFL_OUTCOMES_INTERVAL_HOURS = int(os.getenv("NFL_OUTCOMES_INTERVAL_HOURS", "24"))

# NFL outcomes update configuration
NFL_OUTCOMES_LOOKBACK_WEEKS = int(os.getenv("NFL_OUTCOMES_LOOKBACK_WEEKS", "4"))
DISABLE_NFL_OUTCOMES_INGEST = os.getenv("DISABLE_NFL_OUTCOMES_INGEST", "false").lower() == "true"

# ═══════════════════════════════════════════════════════════════════════
# Asset Symbol Configuration
# ═══════════════════════════════════════════════════════════════════════

def get_crypto_symbols() -> Dict[str, str]:
    """
    Get crypto symbol mappings from env or defaults.
    Format: BTC-USD:BTC-USD,ETH-USD:ETH-USD,...
    """
    raw = os.getenv("CRYPTO_SYMBOLS")
    if raw:
        symbols = {}
        for pair in raw.split(","):
            if ":" in pair:
                key, value = pair.split(":", 1)
                symbols[key.strip()] = value.strip()
        return symbols

    # Default crypto symbols
    return {
        "BTC-USD": "BTC-USD",
        "ETH-USD": "ETH-USD",
        "XMR-USD": "XMR-USD",
    }


def get_equity_symbols() -> Dict[str, str]:
    """
    Get equity symbol mappings from env or defaults.
    Format: NVDA:NVDA,AAPL:AAPL,...
    """
    raw = os.getenv("EQUITY_SYMBOLS")
    if raw:
        symbols = {}
        for pair in raw.split(","):
            if ":" in pair:
                key, value = pair.split(":", 1)
                symbols[key.strip()] = value.strip()
        return symbols

    # Default equity symbols
    return {
        "NVDA": "NVDA",
    }


def get_all_symbols() -> List[str]:
    """Get all configured symbols (crypto + equity)."""
    crypto = list(get_crypto_symbols().keys())
    equity = list(get_equity_symbols().keys())
    return crypto + equity


# ═══════════════════════════════════════════════════════════════════════
# API Configuration
# ═══════════════════════════════════════════════════════════════════════

API_MAX_EVENTS_LIMIT = int(os.getenv("API_MAX_EVENTS_LIMIT", "200"))
API_MAX_NEIGHBORS_LIMIT = int(os.getenv("API_MAX_NEIGHBORS_LIMIT", "50"))
API_MAX_PROJECTIONS_LIMIT = int(os.getenv("API_MAX_PROJECTIONS_LIMIT", "50"))

# Validation constraints
MIN_HORIZON_MINUTES = int(os.getenv("MIN_HORIZON_MINUTES", "1"))
MAX_HORIZON_MINUTES = int(os.getenv("MAX_HORIZON_MINUTES", "43200"))  # 30 days
MIN_LOOKBACK_DAYS = int(os.getenv("MIN_LOOKBACK_DAYS", "1"))
MAX_LOOKBACK_DAYS = int(os.getenv("MAX_LOOKBACK_DAYS", "730"))  # 2 years

# ═══════════════════════════════════════════════════════════════════════
# NFL Event Forecasting Configuration
# ═══════════════════════════════════════════════════════════════════════

# NFL Backfill Configuration
NFL_BACKFILL_SEASONS = int(os.getenv("NFL_BACKFILL_SEASONS", "3"))
NFL_DEFAULT_HORIZON_MINUTES = int(os.getenv("NFL_DEFAULT_HORIZON_MINUTES", str(24 * 60)))  # 1 day

# NFL Game Outcome Configuration
NFL_BASELINE_SCORE = float(os.getenv("NFL_BASELINE_SCORE", "100.0"))
NFL_POINT_DIFF_SCALE = float(os.getenv("NFL_POINT_DIFF_SCALE", "10.0"))

# NFL Event-to-Game Mapping
NFL_MAX_DAYS_AHEAD = int(os.getenv("NFL_MAX_DAYS_AHEAD", "30"))
NFL_MAX_DAYS_BEFORE_GAME = int(os.getenv("NFL_MAX_DAYS_BEFORE_GAME", "7"))
NFL_MIN_DAYS_BEFORE_GAME = int(os.getenv("NFL_MIN_DAYS_BEFORE_GAME", "0"))

# NFL Forecasting Thresholds
NFL_CONFIDENCE_SAMPLE_THRESHOLD = float(os.getenv("NFL_CONFIDENCE_SAMPLE_THRESHOLD", "20.0"))
NFL_CONFIDENCE_SNR_THRESHOLD = float(os.getenv("NFL_CONFIDENCE_SNR_THRESHOLD", "2.0"))

# ESPN API Configuration
ESPN_API_BASE_URL = os.getenv("ESPN_API_BASE_URL", "https://site.api.espn.com/apis/site/v2/sports/football/nfl")
ESPN_API_TIMEOUT = int(os.getenv("ESPN_API_TIMEOUT", "10"))
ESPN_API_MAX_RETRIES = int(os.getenv("ESPN_API_MAX_RETRIES", "3"))
ESPN_USE_OPTIMIZED_FETCH = os.getenv("ESPN_USE_OPTIMIZED_FETCH", "true").lower() in ("true", "1", "yes")

# SportsData.io Configuration
SPORTSDATA_API_KEY = os.getenv("SPORTSDATA_API_KEY", "")
SPORTSDATA_BASE_URL = os.getenv("SPORTSDATA_BASE_URL", "https://api.sportsdata.io/v3/nfl/")
SPORTSDATA_TIMEOUT = int(os.getenv("SPORTSDATA_TIMEOUT", "15"))
SPORTSDATA_MAX_RETRIES = int(os.getenv("SPORTSDATA_MAX_RETRIES", "3"))

# Event backfill settings
NFL_EVENT_BACKFILL_START = os.getenv("NFL_EVENT_BACKFILL_START", "2024-09-01")
NFL_EVENT_LOOKBACK_DAYS = int(os.getenv("NFL_EVENT_LOOKBACK_DAYS", "7"))

# NFL Team Display Names
def get_nfl_team_display_names() -> Dict[str, str]:
    """
    Get NFL team display names from env or defaults.
    Format (env): NFL_TEAM_KC_NAME=Kansas City Chiefs,NFL_TEAM_DAL_NAME=Dallas Cowboys,...
    """
    # Default mapping
    defaults = {
        # NFC East (priority)
        "DAL": "Dallas Cowboys",
        "NYG": "New York Giants",
        "PHI": "Philadelphia Eagles",
        "WAS": "Washington Commanders",  # Historically Washington Redskins/Football Team
        # Other teams
        "KC": "Kansas City Chiefs",
        "SF": "San Francisco 49ers",
        "BUF": "Buffalo Bills",
        "DET": "Detroit Lions",
    }

    # Allow overrides via environment variables
    result = {}
    for abbr, default_name in defaults.items():
        env_key = f"NFL_TEAM_{abbr}_NAME"
        result[abbr] = os.getenv(env_key, default_name)

    return result

# ═══════════════════════════════════════════════════════════════════════
# NFL Feature Engineering Configuration
# ═══════════════════════════════════════════════════════════════════════

NFL_FEATURES_VERSION = os.getenv("NFL_FEATURES_VERSION", "v1.0")
NFL_LOOKBACK_GAMES = int(os.getenv("NFL_LOOKBACK_GAMES", "5"))  # Rolling window for statistics
NFL_MIN_GAMES_FOR_FEATURES = int(os.getenv("NFL_MIN_GAMES_FOR_FEATURES", "3"))  # Minimum history needed
NFL_FORM_WINDOW = int(os.getenv("NFL_FORM_WINDOW", "3"))  # Recent form window

# ═══════════════════════════════════════════════════════════════════════
# Forecast Snapshot Backfill Configuration
# ═══════════════════════════════════════════════════════════════════════

# Backfill time window (in days)
FORECAST_BACKFILL_DAYS = int(os.getenv("FORECAST_BACKFILL_DAYS", "60"))  # Default: 60 days

# Daily snapshot generation
FORECAST_DAILY_SNAPSHOT_ENABLED = os.getenv("FORECAST_DAILY_SNAPSHOT_ENABLED", "true").lower() in ("true", "1", "yes")
FORECAST_DAILY_SNAPSHOT_HOUR = int(os.getenv("FORECAST_DAILY_SNAPSHOT_HOUR", "12"))  # UTC hour for daily snapshots

# Batch size for database inserts
FORECAST_BACKFILL_BATCH_SIZE = int(os.getenv("FORECAST_BACKFILL_BATCH_SIZE", "100"))

# Forecast types to compute
FORECAST_TYPES_ENABLED = os.getenv("FORECAST_TYPES_ENABLED", "ml_model_v2,event_weighted").split(",")

# NFL-specific backfill settings
NFL_FORECAST_BACKFILL_DAYS = int(os.getenv("NFL_FORECAST_BACKFILL_DAYS", "60"))  # Override for NFL
NFL_FORECAST_MIN_EVENT_AGE_HOURS = int(os.getenv("NFL_FORECAST_MIN_EVENT_AGE_HOURS", "1"))  # Min age to backfill
NFL_FORECAST_MAX_EVENTS_PER_DAY = int(os.getenv("NFL_FORECAST_MAX_EVENTS_PER_DAY", "50"))  # Limit events processed

# ═══════════════════════════════════════════════════════════════════════
# Feature flags
# ═══════════════════════════════════════════════════════════════════════

DISABLE_STARTUP_INGESTION = os.getenv("DISABLE_STARTUP_INGESTION", "true").lower() in ("true", "1", "yes")
DISABLE_NFL_ELO_INGEST = os.getenv("DISABLE_NFL_ELO_INGEST", "true").lower() in ("true", "1", "yes")
DISABLE_BAKER_PROJECTIONS = os.getenv("DISABLE_BAKER_PROJECTIONS", "false").lower() in ("true", "1", "yes")
