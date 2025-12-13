# backend/app.py

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg import sql
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from db import get_conn, close_pool
from embeddings import embed_text
from utils.url_utils import canonicalize_url
from utils.team_config import load_team_config

from models.naive_asset_forecaster import forecast_asset
from models.event_return_forecaster import (
    forecast_event_return,
    EventReturnForecastResult,
)
from models.regime_classifier import classify_regime
from models.ml_forecaster import forecast_asset_ml, is_ml_model_available
from numeric.asset_projections import get_latest_projections

# shared config for projections
TEAM_CONFIG = load_team_config()

# ---------------------------------------------------------------------
# Env + FastAPI init
# ---------------------------------------------------------------------

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Import configuration
from config import (
    DISABLE_STARTUP_INGESTION,
    DISABLE_NFL_ELO_INGEST,
    DISABLE_BAKER_PROJECTIONS,
    DISABLE_NFL_OUTCOMES_INGEST,
    DISABLE_NFL_NEWS_INGEST,
    RSS_INGEST_INTERVAL_HOURS,
    CRYPTO_BACKFILL_INTERVAL_HOURS,
    EQUITY_BACKFILL_INTERVAL_HOURS,
    NFL_ELO_BACKFILL_INTERVAL_HOURS,
    BAKER_PROJECTIONS_INTERVAL_HOURS,
    NFL_OUTCOMES_INTERVAL_HOURS,
    NFL_NEWS_INGEST_INTERVAL_HOURS,
    NFL_OUTCOMES_LOOKBACK_WEEKS,
    API_MAX_EVENTS_LIMIT,
    API_MAX_NEIGHBORS_LIMIT,
    API_MAX_PROJECTIONS_LIMIT,
    MIN_HORIZON_MINUTES,
    MAX_HORIZON_MINUTES,
    MIN_LOOKBACK_DAYS,
    MAX_LOOKBACK_DAYS,
    DEFAULT_HORIZON_MINUTES,
    DEFAULT_LOOKBACK_DAYS,
)

app = FastAPI(title="BloombergGPT Semantic Backend")

# Background scheduler for periodic ingestion
scheduler = BackgroundScheduler()


def run_rss_ingest() -> None:
    """Background job to ingest RSS feeds with skip_recent optimization."""
    try:
        from ingest.rss_ingest import main as ingest_main

        print("[scheduler] Running RSS ingestion (skip_recent=True)...")
        ingest_main(skip_recent=True)
        print("[scheduler] RSS ingestion complete.")
    except Exception as e:
        print(f"[scheduler] RSS ingestion error: {e}")


def run_crypto_backfill() -> None:
    """Background job to backfill crypto prices."""
    try:
        from ingest.backfill_crypto_returns import main as backfill_main

        print("[scheduler] Running crypto backfill...")
        backfill_main()
        print("[scheduler] Crypto backfill complete.")
    except Exception as e:
        print(f"[scheduler] Crypto backfill error: {e}")


def run_equity_backfill() -> None:
    """Background job to backfill equity prices (e.g., NVDA)."""
    try:
        from ingest.backfill_equity_returns import main as backfill_main

        print("[scheduler] Running equity backfill...")
        backfill_main()
        print("[scheduler] Equity backfill complete.")
    except Exception as e:
        print(f"[scheduler] Equity backfill error: {e}")


def run_nfl_elo_backfill() -> None:
    """Background job to backfill NFL Elo deltas for selected teams."""
    if DISABLE_NFL_ELO_INGEST:
        print("[scheduler] NFL Elo ingestion disabled (DISABLE_NFL_ELO_INGEST=true)")
        return
    try:
        from ingest.backfill_nfl_elo import main as backfill_main

        print("[scheduler] Running NFL Elo backfill...")
        backfill_main()
        print("[scheduler] NFL Elo backfill complete.")
    except Exception as e:
        print(f"[scheduler] NFL Elo backfill error: {e}")


def run_nfl_news_ingest() -> None:
    """Background job to ingest NFL news from RapidAPI."""
    if DISABLE_NFL_NEWS_INGEST:
        print("[scheduler] NFL News ingestion disabled (DISABLE_NFL_NEWS_INGEST=true)")
        return
    try:
        from ingest.nfl_news_api import main as ingest_main

        print("[scheduler] Running NFL News ingestion (skip_recent=True)...")
        ingest_main(skip_recent=True)
        print("[scheduler] NFL News ingestion complete.")
    except Exception as e:
        print(f"[scheduler] NFL News ingestion error: {e}")


def run_baker_projections() -> None:
    """Background job to ingest Baker NFL projections (win probabilities)."""
    try:
        from ingest.baker_projections import ingest_once

        print("[scheduler] Running Baker projections ingest...")
        ingest_once()
        print("[scheduler] Baker projections ingest complete.")
    except Exception as e:
        print(f"[scheduler] Baker projections error: {e}")


def run_nfl_outcomes_daily() -> None:
    """Background job to fetch recent NFL game outcomes (daily updates)."""
    if DISABLE_NFL_OUTCOMES_INGEST:
        print("[scheduler] NFL outcomes ingestion disabled (DISABLE_NFL_OUTCOMES_INGEST=true)")
        return

    try:
        from utils.nfl_schedule import get_weeks_to_fetch, should_run_nfl_updates
        from ingest.backfill_sportsdata_nfl import backfill_from_sportsdata

        # Check if we're in NFL season
        if not should_run_nfl_updates():
            print("[scheduler] Skipping NFL outcomes (off-season: March-August)")
            return

        # Get current season and weeks to fetch
        season_year, start_week, end_week = get_weeks_to_fetch(lookback_weeks=NFL_OUTCOMES_LOOKBACK_WEEKS)

        print(f"[scheduler] Fetching NFL outcomes for {season_year} weeks {start_week}-{end_week}...")

        # Fetch recent weeks (catches delayed scores and corrections)
        inserted, skipped = backfill_from_sportsdata(
            seasons=[season_year],
            teams=None,  # All configured teams
            weeks_per_season=end_week,  # Fetch up to current week
        )

        print(f"[scheduler] NFL outcomes: {inserted} new, {skipped} duplicates")
    except Exception as e:
        print(f"[scheduler] NFL outcomes error: {e}")


def run_all_ingestion_jobs() -> None:
    """Run all ingestion jobs sequentially in background thread."""
    try:
        print("[scheduler] Starting background ingestion...")
        run_rss_ingest()
        run_nfl_news_ingest()
        run_crypto_backfill()
        run_equity_backfill()
        run_nfl_elo_backfill()
        run_baker_projections()
        run_nfl_outcomes_daily()
        print("[scheduler] ✓ All background ingestion jobs complete")
    except Exception as e:
        print(f"[scheduler] Error in background ingestion: {e}")


@app.on_event("startup")
def startup_event() -> None:
    """Start scheduler and optionally run initial ingestion in background."""
    # Start scheduler immediately (server becomes available quickly)
    scheduler.add_job(run_rss_ingest, "interval", hours=RSS_INGEST_INTERVAL_HOURS, id="rss_ingest")
    scheduler.add_job(run_crypto_backfill, "interval", hours=CRYPTO_BACKFILL_INTERVAL_HOURS, id="crypto_backfill")
    scheduler.add_job(run_equity_backfill, "interval", hours=EQUITY_BACKFILL_INTERVAL_HOURS, id="equity_backfill")

    # Only schedule NFL Elo job if not disabled
    if not DISABLE_NFL_ELO_INGEST:
        scheduler.add_job(run_nfl_elo_backfill, "interval", hours=NFL_ELO_BACKFILL_INTERVAL_HOURS, id="nfl_elo_backfill")
    else:
        print("[scheduler] NFL Elo backfill job not scheduled (DISABLE_NFL_ELO_INGEST=true)")

    if not DISABLE_BAKER_PROJECTIONS:
        scheduler.add_job(run_baker_projections, "interval", hours=BAKER_PROJECTIONS_INTERVAL_HOURS, id="baker_projections")
    else:
        print("[scheduler] Baker projections job not scheduled (DISABLE_BAKER_PROJECTIONS=true)")

    # Schedule NFL game outcomes updates (daily during season)
    if not DISABLE_NFL_OUTCOMES_INGEST:
        scheduler.add_job(run_nfl_outcomes_daily, "interval", hours=NFL_OUTCOMES_INTERVAL_HOURS, id="nfl_outcomes")
    else:
        print("[scheduler] NFL outcomes job not scheduled (DISABLE_NFL_OUTCOMES_INGEST=true)")

    # Schedule NFL News API ingestion (hourly)
    if not DISABLE_NFL_NEWS_INGEST:
        scheduler.add_job(run_nfl_news_ingest, "interval", hours=NFL_NEWS_INGEST_INTERVAL_HOURS, id="nfl_news")
    else:
        print("[scheduler] NFL News job not scheduled (DISABLE_NFL_NEWS_INGEST=true)")

    scheduler.start()
    print(
        "[scheduler] ✓ Started background scheduler "
        "(RSS/Baker/NFL News: hourly, crypto/equity/NFL: daily)"
    )

    # Run initial ingestion in background thread (non-blocking)
    if not DISABLE_STARTUP_INGESTION:
        print("[scheduler] Launching initial ingestion in background (non-blocking)...")
        thread = threading.Thread(target=run_all_ingestion_jobs, daemon=True, name="InitialIngestion")
        thread.start()
    else:
        print("[scheduler] ⚠️  Startup ingestion DISABLED (DISABLE_STARTUP_INGESTION=true)")
        print("[scheduler] Set DISABLE_STARTUP_INGESTION=false to enable automatic ingestion")


@app.on_event("shutdown")
def shutdown_event() -> None:
    """Gracefully close scheduler and connection pool on shutdown."""
    scheduler.shutdown(wait=False)
    close_pool()


# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------


class EventIn(BaseModel):
    timestamp: datetime = Field(..., description="UTC timestamp of the event")
    source: str = Field(..., description="Canonical source name, e.g., 'wired_ai'")
    url: Optional[str] = Field(
        None,
        description="Canonicalized URL of the event (can be null for synthetic events)",
    )
    title: str = Field(..., description="Headline or title of the event")
    summary: str = Field(..., description="Short summary or description")
    raw_text: str = Field(..., description="Raw combined text (title + summary)")
    clean_text: Optional[str] = Field(
        None,
        description="Text fed into embeddings; defaults to raw_text if omitted",
    )
    categories: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class EventCreate(EventIn):
    embed: Optional[List[float]] = Field(
        default=None,
        description=(
            "Optional manual embedding override; if omitted, backend generates one."
        ),
    )


class EventOut(EventIn):
    id: str = Field(..., description="UUID of the event")


class Neighbor(BaseModel):
    id: str
    timestamp: Optional[datetime]
    source: str
    url: Optional[str]
    raw_text: str
    categories: List[str]
    tags: List[str]
    distance: float


class EventReturnForecastOut(BaseModel):
    event_id: str
    symbol: str
    horizon_minutes: int
    expected_return: float
    std_return: float
    p_up: float
    p_down: float
    sample_size: int
    neighbors_used: int
    confidence: float  # Horizon-normalized confidence score (0-1)


class ProjectionOut(BaseModel):
    symbol: str
    as_of: datetime
    horizon_minutes: int
    metric: str
    projected_value: float
    model_source: str
    game_id: Optional[int] = None


class NFLEventForecastOut(BaseModel):
    """NFL event-based forecast response"""
    event_id: str
    team_symbol: str
    next_game_date: Optional[datetime]
    opponent: Optional[str]
    days_until_game: Optional[float]
    win_probability: Optional[float]
    expected_point_diff: Optional[float]
    confidence: float
    similar_events_found: int
    sample_size: int
    forecast_available: bool
    no_game_reason: Optional[str] = None


class NFLTeamForecastOut(BaseModel):
    """Team next game forecast with events"""
    team_symbol: str
    next_game_found: bool
    game_date: Optional[datetime] = None
    days_until_game: Optional[float] = None
    opponent: Optional[str] = None
    event_forecasts_count: int = 0
    aggregated_win_probability: Optional[float] = None
    forecast_confidence: Optional[float] = None
    message: Optional[str] = None


class AssetForecastOut(BaseModel):
    symbol: str
    as_of: str
    horizon_minutes: int
    expected_return: Optional[float]
    direction: Optional[str]
    confidence: float
    lookback_days: int
    n_points: int
    mean_return: Optional[float]
    vol_return: Optional[float]
    features: Dict[str, Any]
    regime: Optional[str] = None
    regime_score: Optional[float] = None
    model_type: Optional[str] = None  # "ml" or "naive"
    model_name: Optional[str] = None  # e.g., "ml_forecaster_7d_rf" or "naive_baseline"


class EventSummary(BaseModel):
    id: str
    timestamp: datetime
    source: str
    url: Optional[str]
    title: str
    summary: str
    categories: List[str]
    tags: List[str]


class HealthCheck(BaseModel):
    status: str
    database: str
    pgvector: str


class EventAnalysisOut(BaseModel):
    event_id: str
    sentiment: str
    impact_score: float
    confidence: float
    reasoning: str
    tags: List[str]
    provider: str


class SentimentOut(BaseModel):
    text: str
    sentiment: str
    provider: str


class NFLMLGameForecastOut(BaseModel):
    """ML-based game forecast response"""
    team_symbol: str
    game_date: datetime
    predicted_winner: str  # "WIN" or "LOSS"
    win_probability: float
    confidence: float
    features_used: int
    model_version: str


class NFLMLUpcomingGamesOut(BaseModel):
    """Upcoming games forecasts for a team"""
    team_symbol: str
    games_found: int
    forecasts: List[NFLMLGameForecastOut]
    message: Optional[str] = None


class NFLMLModelInfoOut(BaseModel):
    """Model metadata and training info"""
    model_version: str
    training_date: Optional[str] = None
    test_accuracy: Optional[float] = None
    train_accuracy: Optional[float] = None
    features_count: int
    feature_names: List[str]
    trained_on: Optional[str] = None  # e.g., "Dallas Cowboys, 15 games"
    hyperparameters: Optional[Dict[str, Any]] = None


class NFLTeamInfo(BaseModel):
    """Basic NFL team information"""
    symbol: str
    abbreviation: str
    display_name: str
    total_games: int
    first_game_date: Optional[datetime] = None
    last_game_date: Optional[datetime] = None


class NFLTeamStats(BaseModel):
    """NFL team statistics"""
    symbol: str
    display_name: str
    total_games: int
    total_wins: int
    total_losses: int
    win_percentage: float
    current_season_wins: int
    current_season_losses: int
    current_season_win_pct: float
    avg_point_differential: float
    current_streak: str  # e.g., "W3" or "L2"
    recent_games: List[Dict[str, Any]]


class NFLGameInfo(BaseModel):
    """Single NFL game information"""
    symbol: str
    game_date: datetime
    opponent: Optional[str] = None
    result: str  # "WIN" or "LOSS"
    point_differential: float
    team_score: Optional[float] = None
    opponent_score: Optional[float] = None


class NFLGamesResponse(BaseModel):
    """Paginated NFL games response"""
    symbol: str
    total_games: int
    games: List[NFLGameInfo]
    page: int
    page_size: int


class ForecastSnapshot(BaseModel):
    """Single forecast snapshot"""
    timestamp: datetime
    forecast_value: float
    confidence: float
    model_source: str
    model_version: Optional[str] = None
    event_id: Optional[str] = None
    event_summary: Optional[str] = None
    sample_size: Optional[int] = None
    target_date: Optional[datetime] = None
    horizon_minutes: Optional[int] = None


class ForecastTimelineOut(BaseModel):
    """Forecast timeline response"""
    symbol: str
    forecast_type: str
    start_date: datetime
    end_date: datetime
    snapshots_count: int
    snapshots: List[ForecastSnapshot]


class EventImpactOut(BaseModel):
    """Event impact analysis response"""
    event_id: str
    event_title: str
    event_timestamp: datetime
    symbol: str

    # Forecast before/after
    forecast_before: Optional[float] = None
    forecast_after: Optional[float] = None
    forecast_change: Optional[float] = None

    # Similar historical events
    similar_events_count: int
    historical_impact_avg: Optional[float] = None

    # Next game context
    next_game_date: Optional[datetime] = None
    days_until_game: Optional[float] = None


# ---------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------


@app.get("/health", response_model=HealthCheck)
def health_check() -> HealthCheck:
    """Check API health, database connectivity, and pgvector extension."""
    db_status = "ok"
    pgvector_status = "ok"

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception:
        db_status = "error"

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                row = cur.fetchone()
                if not row:
                    pgvector_status = "not_installed"
    except Exception:
        pgvector_status = "error"

    overall = "healthy" if db_status == "ok" and pgvector_status == "ok" else "unhealthy"

    return HealthCheck(status=overall, database=db_status, pgvector=pgvector_status)


@app.get("/ingest/health")
def ingest_health() -> Dict[str, Any]:
    """
    Lightweight ingest health snapshot.
    - feed_metadata last_fetched
    - events count
    - asset_returns latest as_of
    - projections latest as_of
    - ingest_status per job
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(last_fetched) as last_fetched FROM feed_metadata")
            fm = cur.fetchone() or {}
            cur.execute("SELECT count(*) AS cnt FROM events")
            ev = cur.fetchone() or {}
            cur.execute("SELECT max(as_of) AS max_as_of FROM asset_returns")
            ar = cur.fetchone() or {}
            cur.execute("SELECT max(as_of) AS max_as_of FROM projections")
            ap = cur.fetchone() or {}
            cur.execute(
                """
                SELECT job_name, last_success, last_error, last_error_message, last_rows_inserted, updated_at
                FROM ingest_status
                """
            )
            status_rows = cur.fetchall() or []

    ingest_status = {}
    for r in status_rows:
        ingest_status[r["job_name"]] = {
            "last_success": r["last_success"],
            "last_error": r["last_error"],
            "last_error_message": r["last_error_message"],
            "last_rows_inserted": r["last_rows_inserted"],
            "updated_at": r["updated_at"],
        }
    return {
        "feed_metadata_last_fetched": fm.get("last_fetched"),
        "events_count": ev.get("cnt", 0),
        "asset_returns_last_as_of": ar.get("max_as_of"),
        "asset_projections_last_as_of": ap.get("max_as_of"),
        "ingest_status": ingest_status,
    }


# ---------------------------------------------------------------------
# Event ingestion + similarity
# ---------------------------------------------------------------------


@app.post("/events")
def create_event(event: EventCreate) -> Dict[str, str]:
    """
    Insert a new event row.
    If no embedding is provided, we generate one from clean_text or raw_text.
    """
    event_id = uuid4()

    # Canonicalize URL if present
    url = canonicalize_url(event.url) if event.url else None

    # Choose text for embeddings and storage
    clean_text = event.clean_text or event.raw_text
    categories = event.categories or []
    tags = event.tags or []

    # Generate embedding if not provided
    if event.embed is not None:
        embed_vector = event.embed
    else:
        embed_vector = embed_text(clean_text)

    # pgvector literal format: [0.1,0.2,...]
    embed_literal = "[" + ",".join(str(x) for x in embed_vector) + "]"

    cols = [
        "id",
        "timestamp",
        "source",
        "url",
        "title",
        "summary",
        "raw_text",
        "clean_text",
        "categories",
        "tags",
        "embed",
    ]
    values = [
        event_id,
        event.timestamp,
        event.source,
        url,
        event.title,
        event.summary,
        event.raw_text,
        clean_text,
        categories,
        tags,
        embed_literal,
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("INSERT INTO events ({}) VALUES ({})").format(
                    sql.SQL(", ").join(sql.Identifier(col) for col in cols),
                    sql.SQL(", ").join(sql.Placeholder() * len(cols)),
                ),
                values,
            )

    return {"id": str(event_id)}


@app.get("/events/recent", response_model=List[EventSummary])
def get_recent_events(
    limit: int = Query(default=50, ge=1, le=API_MAX_EVENTS_LIMIT),
    source: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None, description="Filter by domain: crypto, sports, tech, general"),
    symbol: Optional[str] = Query(default=None, description="Filter by symbol: BTC-USD, NFL:DAL_COWBOYS, etc."),
) -> List[EventSummary]:
    """
    Fetch recent events, optionally filtered by source, domain, or symbol.
    Domain is stored in the categories array.
    Symbol filtering uses text matching (e.g., "Cowboys" for NFL:DAL_COWBOYS).
    Returns newest first.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if source is not None:
                cur.execute(
                    """
                    SELECT id, timestamp, source, url, title, summary, categories, tags, clean_text
                    FROM events
                    WHERE source = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (source, int(limit)),
                )
            elif domain is not None:
                cur.execute(
                    """
                    SELECT id, timestamp, source, url, title, summary, categories, tags, clean_text
                    FROM events
                    WHERE %s = ANY(categories)
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (domain, int(limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT id, timestamp, source, url, title, summary, categories, tags, clean_text
                    FROM events
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
            rows = cur.fetchall()

    # Apply symbol filtering if requested (post-query filtering)
    if symbol is not None:
        from signals.symbol_filter import is_symbol_mentioned

        filtered_rows = []
        for r in rows:
            # Build text to check
            text_to_check = " ".join(filter(None, [
                r.get('title', ''),
                r.get('summary', ''),
                r.get('clean_text', ''),
            ]))

            # Check if this event mentions the symbol
            if is_symbol_mentioned(text_to_check, symbol):
                filtered_rows.append(r)

        rows = filtered_rows

    return [
        EventSummary(
            id=str(r["id"]),
            timestamp=r["timestamp"],
            source=r["source"],
            url=r["url"],
            title=r["title"],
            summary=r["summary"],
            categories=r["categories"] or [],
            tags=r["tags"] or [],
        )
        for r in rows
    ]


@app.get("/events/{event_id}/similar")
def get_similar_events(
    event_id: UUID,
    limit: int = Query(default=10, ge=1, le=API_MAX_NEIGHBORS_LIMIT)
) -> Dict[str, Any]:
    """
    Return nearest neighbors in embedding space for a given event_id.
    Uses vector store (Weaviate or PostgreSQL pgvector).
    """
    from vector_store import get_vector_store

    # Get vector for the anchor event
    vector_store = get_vector_store()
    query_vector = vector_store.get_vector(event_id)

    if not query_vector:
        raise HTTPException(
            status_code=404,
            detail="Event not found or has no embedding",
        )

    # Search for similar vectors
    results = vector_store.search(
        query_vector=query_vector,
        limit=limit,
        exclude_id=event_id,
    )

    # Get full event metadata from PostgreSQL for each result
    event_ids = [r.event_id for r in results]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp, source, url, raw_text, categories, tags
                FROM events
                WHERE id = ANY(%s)
                """,
                (event_ids,),
            )
            rows = cur.fetchall()

    # Build metadata map
    metadata_map = {str(row["id"]): row for row in rows}

    # Merge vector search results with PostgreSQL metadata
    neighbors: List[Neighbor] = []
    for result in results:
        metadata = metadata_map.get(result.event_id)
        if metadata:
            neighbors.append(
                Neighbor(
                    id=result.event_id,
                    timestamp=metadata["timestamp"],
                    source=metadata["source"],
                    url=metadata["url"],
                    raw_text=metadata["raw_text"],
                    categories=metadata["categories"] or [],
                    tags=metadata["tags"] or [],
                    distance=result.distance,
                )
            )

    return {"event_id": str(event_id), "neighbors": neighbors}


# ---------------------------------------------------------------------
# Asset-level naive forecaster
# ---------------------------------------------------------------------


@app.get("/forecast/asset", response_model=AssetForecastOut)
def forecast_asset_endpoint(
    symbol: str = Query(..., description="e.g. BTC-USD", min_length=1, max_length=50),
    horizon_minutes: int = Query(
        DEFAULT_HORIZON_MINUTES,
        description="Forecast horizon in minutes",
        ge=MIN_HORIZON_MINUTES,
        le=MAX_HORIZON_MINUTES
    ),
    lookback_days: int = Query(
        DEFAULT_LOOKBACK_DAYS,
        description="Lookback window for features",
        ge=MIN_LOOKBACK_DAYS,
        le=MAX_LOOKBACK_DAYS
    ),
) -> AssetForecastOut:
    """
    Asset forecaster with ML model fallback to naive baseline.

    Strategy:
    1. Try ML model if available for this (symbol, horizon)
    2. If ML model unavailable or fails, fallback to naive baseline
    3. Always return valid forecast (never fail)

    Example:
      GET /forecast/asset?symbol=BTC-USD&horizon_minutes=10080&lookback_days=60

    Response includes:
      - model_type: "ml" or "naive" (which model was used)
      - model_name: specific model identifier
      - All standard forecast fields (direction, confidence, etc.)

    Validation:
      - horizon_minutes: 1 to 43200 (30 days)
      - lookback_days: 1 to 730 (2 years)
    """
    as_of = datetime.now(tz=timezone.utc)

    # Try ML model first (if available for this symbol + horizon)
    ml_result = None
    if is_ml_model_available(symbol, horizon_minutes):
        ml_result = forecast_asset_ml(
            symbol=symbol,
            as_of=as_of,
            horizon_minutes=horizon_minutes,
            lookback_days=lookback_days,
        )

    # Use ML result if successful, otherwise fallback to naive
    if ml_result:
        asset_res = ml_result
        model_type = "ml"
        model_name = f"ml_forecaster_{horizon_minutes // 1440}d_rf"
    else:
        asset_res = forecast_asset(
            symbol=symbol,
            as_of=as_of,
            horizon_minutes=horizon_minutes,
            lookback_days=lookback_days,
        )
        model_type = "naive"
        model_name = "naive_baseline"

    # Get market regime
    regime_res = classify_regime(symbol, as_of)

    # Build response
    payload = asset_res.to_dict()
    payload["regime"] = regime_res.regime
    payload["regime_score"] = regime_res.score
    payload["model_type"] = model_type
    payload["model_name"] = model_name

    return AssetForecastOut(**payload)


# ---------------------------------------------------------------------
# Event-conditioned (semantic) forecaster
# ---------------------------------------------------------------------


@app.get("/forecast/event/{event_id}", response_model=EventReturnForecastOut)
def forecast_event_endpoint(
    event_id: UUID,
    symbol: str = Query(..., min_length=1, max_length=50),
    horizon_minutes: int = Query(
        DEFAULT_HORIZON_MINUTES,
        ge=MIN_HORIZON_MINUTES,
        le=MAX_HORIZON_MINUTES
    ),
    k_neighbors: int = Query(default=25, ge=1, le=100),
    lookback_days: int = Query(default=365, ge=MIN_LOOKBACK_DAYS, le=MAX_LOOKBACK_DAYS),
    price_window_minutes: int = Query(default=60, ge=1, le=1440),
    alpha: float = Query(default=0.5, ge=0.0, le=10.0),
) -> EventReturnForecastOut:
    """
    Event-based forecaster.

    Given a stored event_id and an asset symbol/horizon, this:
      - finds semantically similar past events,
      - looks up realized returns around those events,
      - computes a distance-weighted forecast.
    """
    result: EventReturnForecastResult = forecast_event_return(
        event_id=event_id,
        symbol=symbol,
        horizon_minutes=horizon_minutes,
        k_neighbors=k_neighbors,
        lookback_days=lookback_days,
        price_window_minutes=price_window_minutes,
        alpha=alpha,
    )

    return EventReturnForecastOut(
        event_id=str(result.event_id),
        symbol=result.symbol,
        horizon_minutes=result.horizon_minutes,
        expected_return=result.expected_return,
        std_return=result.std_return,
        p_up=result.p_up,
        p_down=result.p_down,
        sample_size=result.sample_size,
        neighbors_used=result.neighbors_used,
    )


# ---------------------------------------------------------------------
# NFL Forecasting
# ---------------------------------------------------------------------


@app.get("/forecast/nfl/event/{event_id}", response_model=NFLEventForecastOut)
def forecast_nfl_event_endpoint(
    event_id: UUID,
    team_symbol: str = Query(..., regex="^NFL:[A-Z_]+$", description="Team symbol (e.g., NFL:DAL_COWBOYS)"),
    k_neighbors: int = Query(25, ge=1, le=100, description="Number of similar events to use"),
    lookback_days: int = Query(365, ge=30, le=1095, description="Days to look back for similar events"),
) -> NFLEventForecastOut:
    """
    Forecast how a sports event will affect a team's next game outcome.

    This endpoint uses semantic similarity to find similar historical events
    and predicts the likely game outcome based on what happened after those events.

    **How it works:**
    1. Finds the team's next scheduled game after the event
    2. Searches for semantically similar historical events
    3. Looks at game outcomes after those similar events
    4. Returns a weighted prediction of win probability

    **Example:**
    - Event: "Cowboys QB Dak Prescott injured in practice"
    - System finds similar injury events from the past
    - Checks Cowboys' win rate after those events
    - Returns: 35% win probability (injuries typically hurt performance)
    """
    from models.nfl_event_forecaster import forecast_nfl_event

    result = forecast_nfl_event(
        event_id=event_id,
        team_symbol=team_symbol,
        k_neighbors=k_neighbors,
        lookback_days=lookback_days,
    )

    return NFLEventForecastOut(
        event_id=str(result.event_id),
        team_symbol=result.team_symbol,
        next_game_date=result.next_game_date,
        opponent=result.opponent,
        days_until_game=result.days_until_game,
        win_probability=result.win_probability,
        expected_point_diff=result.expected_point_diff,
        confidence=result.confidence,
        similar_events_found=result.similar_events_found,
        sample_size=result.sample_size,
        forecast_available=result.forecast_available,
        no_game_reason=result.no_game_reason,
    )


@app.get("/forecast/nfl/team/{team_symbol}/next-game", response_model=NFLTeamForecastOut)
def forecast_team_next_game_endpoint(
    team_symbol: str,
    include_recent_events: bool = Query(True, description="Include forecasts from recent events"),
    max_event_age_days: int = Query(7, ge=1, le=30, description="Max days back to look for events"),
) -> NFLTeamForecastOut:
    """
    Get a comprehensive forecast for a team's next game.

    This endpoint:
    1. Finds the team's next scheduled game
    2. Identifies recent sports events related to the team
    3. Generates win probability forecasts from each event
    4. Aggregates them into a single prediction

    **Use case:** Dynamic dashboard that updates as new events occur

    **Example response:**
    ```json
    {
      "team_symbol": "NFL:DAL_COWBOYS",
      "next_game_found": true,
      "game_date": "2024-11-24T18:00:00Z",
      "days_until_game": 3.5,
      "opponent": "WAS",
      "event_forecasts_count": 4,
      "aggregated_win_probability": 0.62,
      "forecast_confidence": 0.75
    }
    ```

    **Interpretation:**
    - Based on 4 recent events (injuries, roster moves, etc.)
    - System predicts 62% chance Cowboys win
    - 75% confidence in this prediction
    """
    from models.nfl_event_forecaster import forecast_team_next_game

    result = forecast_team_next_game(
        team_symbol=team_symbol,
        include_recent_events=include_recent_events,
        max_event_age_days=max_event_age_days,
    )

    return NFLTeamForecastOut(
        team_symbol=result["team_symbol"],
        next_game_found=result["next_game_found"],
        game_date=result.get("game_date"),
        days_until_game=result.get("days_until_game"),
        opponent=result.get("opponent"),
        event_forecasts_count=result.get("event_forecasts_count", 0),
        aggregated_win_probability=result.get("aggregated_win_probability"),
        forecast_confidence=result.get("forecast_confidence"),
        message=result.get("message"),
    )


# ---------------------------------------------------------------------
# NFL ML Forecasting (Statistical Model)
# ---------------------------------------------------------------------


@app.get("/forecast/nfl/ml/game", response_model=NFLMLGameForecastOut)
def forecast_nfl_ml_game_endpoint(
    team_symbol: str = Query(
        ...,
        regex="^NFL:[A-Z_]+$",
        description="Team symbol (e.g., NFL:DAL_COWBOYS)",
    ),
    game_date: datetime = Query(
        ...,
        description="Game date (ISO 8601 format, UTC)",
    ),
) -> NFLMLGameForecastOut:
    """
    Predict a specific NFL game outcome using the trained ML model.

    **Model:** Logistic Regression with 9 statistical features
    **Accuracy:** 66.7% on test set (no overfitting)
    **Features:** win%, points, differentials, streaks, volatility

    **Example:**
    ```
    GET /forecast/nfl/ml/game?team_symbol=NFL:DAL_COWBOYS&game_date=2024-11-28T18:00:00Z
    ```

    **Response:**
    ```json
    {
      "team_symbol": "NFL:DAL_COWBOYS",
      "game_date": "2024-11-28T18:00:00Z",
      "predicted_winner": "WIN",
      "win_probability": 0.623,
      "confidence": 0.623,
      "features_used": 9,
      "model_version": "v1.0"
    }
    ```

    **Use case:** Get prediction for a specific scheduled game
    """
    from models.nfl_ml_forecaster import get_forecaster

    # Ensure game_date is timezone-aware
    if game_date.tzinfo is None:
        game_date = game_date.replace(tzinfo=timezone.utc)

    forecaster = get_forecaster()
    result = forecaster.predict(symbol=team_symbol, game_date=game_date)

    return NFLMLGameForecastOut(
        team_symbol=team_symbol,
        game_date=game_date,
        predicted_winner=result["predicted_winner"],
        win_probability=result["win_probability"],
        confidence=result["confidence"],
        features_used=result["features_used"],
        model_version=result["model_version"],
    )


@app.get("/forecast/nfl/ml/team/{team_symbol}/upcoming", response_model=NFLMLUpcomingGamesOut)
def forecast_nfl_ml_upcoming_endpoint(
    team_symbol: str,
    limit: int = Query(5, ge=1, le=10, description="Max number of upcoming games to forecast"),
) -> NFLMLUpcomingGamesOut:
    """
    Forecast upcoming games for a team using the trained ML model.

    This endpoint:
    1. Queries asset_returns for upcoming game dates
    2. Runs ML prediction for each game
    3. Returns forecasts sorted by date

    **Example:**
    ```
    GET /forecast/nfl/ml/team/NFL:DAL_COWBOYS/upcoming?limit=3
    ```

    **Response:**
    ```json
    {
      "team_symbol": "NFL:DAL_COWBOYS",
      "games_found": 3,
      "forecasts": [
        {
          "team_symbol": "NFL:DAL_COWBOYS",
          "game_date": "2024-11-28T18:00:00Z",
          "predicted_winner": "WIN",
          "win_probability": 0.623,
          "confidence": 0.623,
          "features_used": 9,
          "model_version": "v1.0"
        },
        ...
      ]
    }
    ```

    **Use case:** Team dashboard showing predicted outcomes for all upcoming games
    """
    from models.nfl_ml_forecaster import get_forecaster

    # Query upcoming games from asset_returns
    now = datetime.now(tz=timezone.utc)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT as_of
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of > %s
                ORDER BY as_of ASC
                LIMIT %s
                """,
                (team_symbol, now, limit),
            )
            rows = cur.fetchall()

    if not rows:
        return NFLMLUpcomingGamesOut(
            team_symbol=team_symbol,
            games_found=0,
            forecasts=[],
            message="No upcoming games found in asset_returns table",
        )

    # Generate forecasts for each game
    forecaster = get_forecaster()
    forecasts = []

    for row in rows:
        game_date = row["as_of"]
        result = forecaster.predict(symbol=team_symbol, game_date=game_date)

        forecasts.append(
            NFLMLGameForecastOut(
                team_symbol=team_symbol,
                game_date=game_date,
                predicted_winner=result["predicted_winner"],
                win_probability=result["win_probability"],
                confidence=result["confidence"],
                features_used=result["features_used"],
                model_version=result["model_version"],
            )
        )

    return NFLMLUpcomingGamesOut(
        team_symbol=team_symbol,
        games_found=len(forecasts),
        forecasts=forecasts,
    )


@app.get("/forecast/nfl/ml/model/info", response_model=NFLMLModelInfoOut)
def get_nfl_ml_model_info_endpoint() -> NFLMLModelInfoOut:
    """
    Get metadata about the trained NFL ML model.

    Returns:
    - Model version
    - Training date
    - Accuracy metrics
    - Feature names
    - Hyperparameters

    **Example:**
    ```
    GET /forecast/nfl/ml/model/info
    ```

    **Response:**
    ```json
    {
      "model_version": "v1.0",
      "training_date": "2024-12-10T03:45:00Z",
      "test_accuracy": 0.667,
      "train_accuracy": 0.667,
      "features_count": 9,
      "feature_names": ["win_pct", "pts_for_avg", ...],
      "trained_on": "Dallas Cowboys, 15 games (2024-2025)",
      "hyperparameters": {
        "model": "LogisticRegression",
        "penalty": "l2",
        "C": 0.1,
        "solver": "lbfgs"
      }
    }
    ```

    **Use case:** Model transparency, debugging, versioning
    """
    from models.nfl_ml_forecaster import get_forecaster

    forecaster = get_forecaster()
    metadata = forecaster.get_metadata()

    return NFLMLModelInfoOut(
        model_version=forecaster.version,
        training_date=metadata.get("training_date"),
        test_accuracy=metadata.get("test_accuracy"),
        train_accuracy=metadata.get("train_accuracy"),
        features_count=len(forecaster.feature_names),
        feature_names=forecaster.feature_names,
        trained_on=metadata.get("trained_on"),
        hyperparameters=metadata.get("hyperparameters"),
    )


# ---------------------------------------------------------------------
# Projections (Baker, etc.)
# ---------------------------------------------------------------------


@app.get("/projections/latest", response_model=List[ProjectionOut])
def get_latest_projections_endpoint(
    symbol: str = Query(..., description="Target ID, e.g., NFL:KC_CHIEFS", min_length=1, max_length=100),
    metric: str = Query("win_prob", description="Projection metric, e.g., win_prob", min_length=1, max_length=50),
    limit: int = Query(5, ge=1, le=API_MAX_PROJECTIONS_LIMIT, description="Max rows to return"),
) -> List[ProjectionOut]:
    rows = get_latest_projections(symbol=symbol, metric=metric, limit=limit)
    if not rows:
        return []

    results: List[ProjectionOut] = []
    for row in rows:
        results.append(
            ProjectionOut(
                symbol=row["symbol"],
                as_of=row["as_of"],
                horizon_minutes=row["horizon_minutes"],
                metric=row["metric"],
                projected_value=row["projected_value"],
                model_source=row["model_source"],
                game_id=row.get("game_id"),
                run_id=row.get("run_id"),
                opponent=row.get("opponent"),
                opponent_name=row.get("opponent_name"),
                meta=row.get("meta"),
            )
        )
    return results


@app.get("/projections/teams")
def get_projection_teams() -> Dict[str, str]:
    """
    Return available team abbreviations -> target IDs for projections.
    Sourced from BAKER_TEAM_MAP env or defaults.
    """
    return TEAM_CONFIG


@app.get("/symbols/available")
def get_available_symbols() -> Dict[str, Any]:
    """
    Return all available symbols for forecasting, grouped by type.
    This allows the frontend to dynamically discover available assets.
    """
    from config import get_crypto_symbols, get_equity_symbols, get_all_symbols

    return {
        "all": get_all_symbols(),
        "crypto": list(get_crypto_symbols().keys()),
        "equity": list(get_equity_symbols().keys()),
    }


@app.get("/horizons/available")
def get_available_horizons() -> List[Dict[str, Any]]:
    """
    Return available forecast horizons.

    Currently only 24h (1440 minutes) has training data.
    This endpoint allows the frontend to dynamically discover capabilities.
    """
    # Query database to check which horizons have data
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT horizon_minutes
                FROM asset_returns
                ORDER BY horizon_minutes
                """
            )
            rows = cur.fetchall()

    available_horizons = []
    for row in rows:
        minutes = row["horizon_minutes"]
        if minutes == 60:
            label = "1 hour"
        elif minutes == 1440:
            label = "24 hours"
        elif minutes == 10080:
            label = "1 week"
        elif minutes == 43200:
            label = "30 days"
        else:
            hours = minutes / 60
            label = f"{hours:.1f} hours" if hours < 24 else f"{minutes // 1440} days"

        available_horizons.append({
            "value": minutes,
            "label": label,
            "available": True,
        })

    return available_horizons


@app.get("/sources/available")
def get_available_sources() -> List[Dict[str, str]]:
    """
    Return all RSS sources that have been ingested.
    This allows the frontend to dynamically populate source filters.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT source, COUNT(*) as count
                FROM events
                GROUP BY source
                ORDER BY count DESC
                """
            )
            rows = cur.fetchall()

    return [
        {"value": row["source"], "label": row["source"].replace("_", " ").title(), "count": row["count"]}
        for row in rows
    ]


# ---------------------------------------------------------------------
# LLM-powered analysis endpoints
# ---------------------------------------------------------------------


@app.get("/analyze/event/{event_id}", response_model=EventAnalysisOut)
def analyze_event_endpoint(
    event_id: UUID,
    symbol: str = "BTC-USD",
    provider: str = "claude",
) -> EventAnalysisOut:
    """
    Analyze an event for market impact using an LLM.

    Providers: claude (default), openai, gemini
    """
    # Fetch event text
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, summary, raw_text FROM events WHERE id = %s",
                (event_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Event not found")

    event_text = row["raw_text"] or f"{row['title']}\n\n{row['summary']}"

    try:
        from llm import analyze_event

        result = analyze_event(event_text, symbol=symbol, provider=provider)

        return EventAnalysisOut(
            event_id=str(event_id),
            sentiment=result.get("sentiment", "neutral"),
            impact_score=float(result.get("impact_score", 0.0)),
            confidence=float(result.get("confidence", 0.0)),
            reasoning=result.get("reasoning", ""),
            tags=result.get("tags", []),
            provider=provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=f"LLM provider error: {e}")
    except Exception as e:
        print(f"[llm] Unexpected error in analyze_event: {e}")
        raise HTTPException(status_code=503, detail="LLM provider error")


@app.post("/analyze/sentiment", response_model=SentimentOut)
def analyze_sentiment_endpoint(
    text: str = Query(..., min_length=1),
    provider: str = "gemini",
) -> SentimentOut:
    """
    Quick sentiment classification.

    Providers: gemini (default - fast), claude, openai
    """
    try:
        from llm import classify_sentiment

        sentiment = classify_sentiment(text, provider=provider)

        return SentimentOut(
            text=text[:100] + "..." if len(text) > 100 else text,
            sentiment=sentiment,
            provider=provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=f"LLM provider error: {e}")
    except Exception as e:
        print(f"[llm] Unexpected error in classify_sentiment: {e}")
        raise HTTPException(status_code=503, detail="LLM provider error")


# ---------------------------------------------------------------------
# NFL Team Management & Statistics
# ---------------------------------------------------------------------


@app.get("/nfl/teams", response_model=List[NFLTeamInfo])
def get_nfl_teams() -> List[NFLTeamInfo]:
    """
    Get list of all NFL teams with basic information.

    Returns metadata for each team including total games, date ranges, and display names.
    Teams are sorted by total games (most data first).

    **Example:**
    ```
    GET /nfl/teams
    ```

    **Response:**
    ```json
    [
      {
        "symbol": "NFL:DAL_COWBOYS",
        "abbreviation": "DAL",
        "display_name": "Dallas Cowboys",
        "total_games": 215,
        "first_game_date": "2012-09-09T17:00:00Z",
        "last_game_date": "2024-12-08T18:00:00Z"
      },
      ...
    ]
    ```
    """
    from config import get_nfl_team_display_names

    team_names = get_nfl_team_display_names()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get all NFL team symbols and their game counts
            cur.execute(
                """
                SELECT
                    symbol,
                    COUNT(*) as total_games,
                    MIN(as_of) as first_game,
                    MAX(as_of) as last_game
                FROM asset_returns
                WHERE symbol LIKE 'NFL:%'
                GROUP BY symbol
                ORDER BY total_games DESC
                """
            )
            rows = cur.fetchall()

    teams = []
    for row in rows:
        symbol = row["symbol"]
        # Extract abbreviation from symbol (e.g., "NFL:DAL_COWBOYS" -> "DAL")
        if ":" in symbol:
            parts = symbol.split(":", 1)[1]  # "DAL_COWBOYS"
            abbr = parts.split("_")[0]  # "DAL"
        else:
            abbr = symbol

        display_name = team_names.get(abbr, abbr)

        teams.append(
            NFLTeamInfo(
                symbol=symbol,
                abbreviation=abbr,
                display_name=display_name,
                total_games=row["total_games"],
                first_game_date=row["first_game"],
                last_game_date=row["last_game"],
            )
        )

    return teams


@app.get("/nfl/teams/{team_symbol}/stats", response_model=NFLTeamStats)
def get_nfl_team_stats(team_symbol: str) -> NFLTeamStats:
    """
    Get detailed statistics for a specific NFL team.

    Includes:
    - Overall win/loss record
    - Current season (2024) record
    - Average point differential
    - Current win/loss streak
    - Last 10 games

    **Example:**
    ```
    GET /nfl/teams/NFL:DAL_COWBOYS/stats
    ```

    **Response:**
    ```json
    {
      "symbol": "NFL:DAL_COWBOYS",
      "display_name": "Dallas Cowboys",
      "total_games": 215,
      "total_wins": 120,
      "total_losses": 95,
      "win_percentage": 0.558,
      "current_season_wins": 5,
      "current_season_losses": 8,
      "current_season_win_pct": 0.385,
      "avg_point_differential": 2.3,
      "current_streak": "L5",
      "recent_games": [...]
    }
    ```
    """
    from config import get_nfl_team_display_names

    team_names = get_nfl_team_display_names()

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get overall stats
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_games,
                    SUM(CASE WHEN realized_return > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN realized_return < 0 THEN 1 ELSE 0 END) as losses,
                    AVG(price_end - price_start) as avg_point_diff
                FROM asset_returns
                WHERE symbol = %s
                """,
                (team_symbol,),
            )
            overall = cur.fetchone()

            if not overall or overall["total_games"] == 0:
                raise HTTPException(status_code=404, detail=f"Team {team_symbol} not found")

            # Get current season stats (2024)
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_games,
                    SUM(CASE WHEN realized_return > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN realized_return < 0 THEN 1 ELSE 0 END) as losses
                FROM asset_returns
                WHERE symbol = %s
                  AND EXTRACT(YEAR FROM as_of) = 2024
                """,
                (team_symbol,),
            )
            season = cur.fetchone()

            # Get last 10 games for streak calculation and display
            cur.execute(
                """
                SELECT
                    as_of,
                    realized_return,
                    price_end - price_start as point_diff
                FROM asset_returns
                WHERE symbol = %s
                ORDER BY as_of DESC
                LIMIT 10
                """,
                (team_symbol,),
            )
            recent = cur.fetchall()

    # Calculate win percentage
    total_games = overall["total_games"]
    wins = overall["wins"]
    losses = overall["losses"]
    win_pct = wins / total_games if total_games > 0 else 0.0

    # Current season stats
    season_games = season["total_games"] if season else 0
    season_wins = season["wins"] if season else 0
    season_losses = season["losses"] if season else 0
    season_win_pct = season_wins / season_games if season_games > 0 else 0.0

    # Calculate current streak
    streak = ""
    if recent:
        streak_count = 0
        streak_type = "W" if recent[0]["realized_return"] > 0 else "L"

        for game in recent:
            game_type = "W" if game["realized_return"] > 0 else "L"
            if game_type == streak_type:
                streak_count += 1
            else:
                break

        streak = f"{streak_type}{streak_count}"

    # Format recent games
    recent_games = []
    for game in recent:
        result = "WIN" if game["realized_return"] > 0 else "LOSS"
        recent_games.append({
            "date": game["as_of"].isoformat(),
            "result": result,
            "point_differential": float(game["point_diff"]),
        })

    # Extract abbreviation and display name
    abbr = team_symbol.split(":", 1)[1].split("_")[0] if ":" in team_symbol else team_symbol
    display_name = team_names.get(abbr, abbr)

    return NFLTeamStats(
        symbol=team_symbol,
        display_name=display_name,
        total_games=total_games,
        total_wins=wins,
        total_losses=losses,
        win_percentage=win_pct,
        current_season_wins=season_wins,
        current_season_losses=season_losses,
        current_season_win_pct=season_win_pct,
        avg_point_differential=float(overall["avg_point_diff"]),
        current_streak=streak,
        recent_games=recent_games,
    )


@app.get("/nfl/teams/{team_symbol}/games", response_model=NFLGamesResponse)
def get_nfl_team_games(
    team_symbol: str,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Games per page"),
    season: Optional[int] = Query(None, ge=2012, le=2030, description="Filter by season year"),
    outcome: Optional[str] = Query(None, regex="^(win|loss|all)$", description="Filter by outcome: win, loss, all"),
) -> NFLGamesResponse:
    """
    Get paginated game history for an NFL team.

    Supports filtering by season and outcome (win/loss).
    Games are returned newest first.

    **Parameters:**
    - `page`: Page number (default: 1)
    - `page_size`: Games per page (default: 20, max: 100)
    - `season`: Filter by year (optional)
    - `outcome`: Filter by result - "win", "loss", or "all" (optional)

    **Example:**
    ```
    GET /nfl/teams/NFL:DAL_COWBOYS/games?page=1&page_size=10&season=2024&outcome=win
    ```

    **Response:**
    ```json
    {
      "symbol": "NFL:DAL_COWBOYS",
      "total_games": 215,
      "games": [
        {
          "symbol": "NFL:DAL_COWBOYS",
          "game_date": "2024-12-08T18:00:00Z",
          "result": "LOSS",
          "point_differential": -13.0,
          "team_score": 14.0,
          "opponent_score": 27.0
        },
        ...
      ],
      "page": 1,
      "page_size": 10
    }
    ```
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Build WHERE clause
            where_clauses = ["symbol = %s"]
            params = [team_symbol]

            if season is not None:
                where_clauses.append("EXTRACT(YEAR FROM as_of) = %s")
                params.append(season)

            if outcome and outcome != "all":
                if outcome == "win":
                    where_clauses.append("realized_return > 0")
                elif outcome == "loss":
                    where_clauses.append("realized_return < 0")

            where_sql = " AND ".join(where_clauses)

            # Get total count
            count_query = f"SELECT COUNT(*) as total FROM asset_returns WHERE {where_sql}"
            cur.execute(count_query, params)
            total_row = cur.fetchone()
            total_games = total_row["total"] if total_row else 0

            # Get paginated games
            offset = (page - 1) * page_size
            games_query = f"""
                SELECT
                    as_of,
                    realized_return,
                    price_start,
                    price_end
                FROM asset_returns
                WHERE {where_sql}
                ORDER BY as_of DESC
                LIMIT %s OFFSET %s
            """
            cur.execute(games_query, params + [page_size, offset])
            rows = cur.fetchall()

    games = []
    for row in rows:
        result = "WIN" if row["realized_return"] > 0 else "LOSS"
        point_diff = row["price_end"] - row["price_start"]

        # Calculate scores from baseline (100)
        # price_end = 100 + point_differential (team's final score offset)
        # For wins: team scored more, point_diff is positive
        # For losses: team scored less, point_diff is negative
        if result == "WIN":
            team_score = 100 + abs(point_diff) / 2
            opponent_score = 100 - abs(point_diff) / 2
        else:
            team_score = 100 - abs(point_diff) / 2
            opponent_score = 100 + abs(point_diff) / 2

        games.append(
            NFLGameInfo(
                symbol=team_symbol,
                game_date=row["as_of"],
                result=result,
                point_differential=float(point_diff),
                team_score=float(team_score) - 100,  # Remove baseline to show actual differential
                opponent_score=float(opponent_score) - 100,  # Remove baseline
            )
        )

    return NFLGamesResponse(
        symbol=team_symbol,
        total_games=total_games,
        games=games,
        page=page,
        page_size=page_size,
    )


@app.get("/nfl/games/recent", response_model=List[NFLGameInfo])
def get_recent_nfl_games(
    limit: int = Query(20, ge=1, le=100, description="Number of games to return"),
    team: Optional[str] = Query(None, description="Filter by team symbol (optional)"),
) -> List[NFLGameInfo]:
    """
    Get recent NFL games across all teams.

    Returns the most recent games, optionally filtered by team.
    Games are sorted newest first.

    **Example:**
    ```
    GET /nfl/games/recent?limit=10
    GET /nfl/games/recent?limit=5&team=NFL:DAL_COWBOYS
    ```

    **Response:**
    ```json
    [
      {
        "symbol": "NFL:DAL_COWBOYS",
        "game_date": "2024-12-08T18:00:00Z",
        "result": "LOSS",
        "point_differential": -13.0,
        "team_score": 14.0,
        "opponent_score": 27.0
      },
      ...
    ]
    ```
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if team:
                cur.execute(
                    """
                    SELECT
                        symbol,
                        as_of,
                        realized_return,
                        price_start,
                        price_end
                    FROM asset_returns
                    WHERE symbol = %s
                    ORDER BY as_of DESC
                    LIMIT %s
                    """,
                    (team, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        symbol,
                        as_of,
                        realized_return,
                        price_start,
                        price_end
                    FROM asset_returns
                    WHERE symbol LIKE 'NFL:%'
                    ORDER BY as_of DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

    games = []
    for row in rows:
        result = "WIN" if row["realized_return"] > 0 else "LOSS"
        point_diff = row["price_end"] - row["price_start"]

        # Calculate scores from baseline (100)
        if result == "WIN":
            team_score = 100 + abs(point_diff) / 2
            opponent_score = 100 - abs(point_diff) / 2
        else:
            team_score = 100 - abs(point_diff) / 2
            opponent_score = 100 + abs(point_diff) / 2

        games.append(
            NFLGameInfo(
                symbol=row["symbol"],
                game_date=row["as_of"],
                result=result,
                point_differential=float(point_diff),
                team_score=float(team_score) - 100,  # Remove baseline
                opponent_score=float(opponent_score) - 100,  # Remove baseline
            )
        )

    return games


# ---------------------------------------------------------------------
# Forecast Timeline & Event Impact Endpoints
# ---------------------------------------------------------------------


@app.get("/nfl/teams/{symbol}/forecast-timeline", response_model=ForecastTimelineOut)
def get_forecast_timeline(
    symbol: str,
    forecast_type: str = Query("win_probability", description="Forecast type (e.g., 'win_probability')"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    model_source: Optional[str] = Query(None, description="Filter by model source (e.g., 'event_weighted', 'ml_model_v2')"),
) -> ForecastTimelineOut:
    """
    Get forecast timeline showing how predictions evolved over time.

    Returns a time series of forecast snapshots, enabling visualization of:
    - How forecasts changed as new events occurred
    - Comparison of different forecast models over time
    - Event-triggered forecast updates vs daily baseline

    **Example:**
    ```
    GET /nfl/teams/NFL:DAL_COWBOYS/forecast-timeline?days=30&forecast_type=win_probability
    GET /nfl/teams/NFL:DAL_COWBOYS/forecast-timeline?days=7&model_source=event_weighted
    ```

    **Response:**
    ```json
    {
      "symbol": "NFL:DAL_COWBOYS",
      "forecast_type": "win_probability",
      "start_date": "2025-11-11T00:00:00Z",
      "end_date": "2025-12-11T00:00:00Z",
      "snapshots_count": 45,
      "snapshots": [
        {
          "timestamp": "2025-12-10T14:23:00Z",
          "forecast_value": 0.58,
          "confidence": 0.72,
          "model_source": "event_weighted",
          "model_version": "v1.0",
          "event_id": "123e4567-e89b-12d3-a456-426614174000",
          "event_summary": "Dak Prescott injury update: expected to play Sunday",
          "sample_size": 42,
          "target_date": "2025-12-15T18:00:00Z",
          "horizon_minutes": 7560
        },
        ...
      ]
    }
    ```

    **Use case:** Timeline chart showing forecast evolution with event markers
    """
    now = datetime.now(tz=timezone.utc)
    start_date = now - timedelta(days=days)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Build query with optional model_source filter
            if model_source:
                cur.execute(
                    """
                    SELECT
                        snapshot_at,
                        forecast_value,
                        confidence,
                        model_source,
                        model_version,
                        event_id,
                        event_summary,
                        sample_size,
                        target_date,
                        horizon_minutes
                    FROM forecast_snapshots
                    WHERE symbol = %s
                      AND forecast_type = %s
                      AND model_source = %s
                      AND snapshot_at BETWEEN %s AND %s
                    ORDER BY snapshot_at ASC
                    """,
                    (symbol, forecast_type, model_source, start_date, now),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        snapshot_at,
                        forecast_value,
                        confidence,
                        model_source,
                        model_version,
                        event_id,
                        event_summary,
                        sample_size,
                        target_date,
                        horizon_minutes
                    FROM forecast_snapshots
                    WHERE symbol = %s
                      AND forecast_type = %s
                      AND snapshot_at BETWEEN %s AND %s
                    ORDER BY snapshot_at ASC
                    """,
                    (symbol, forecast_type, start_date, now),
                )

            rows = cur.fetchall()

    snapshots = []
    for row in rows:
        snapshots.append(
            ForecastSnapshot(
                timestamp=row["snapshot_at"],
                forecast_value=float(row["forecast_value"]),
                confidence=float(row["confidence"]) if row["confidence"] is not None else 0.0,
                model_source=row["model_source"],
                model_version=row["model_version"],
                event_id=str(row["event_id"]) if row["event_id"] else None,
                event_summary=row["event_summary"],
                sample_size=row["sample_size"],
                target_date=row["target_date"],
                horizon_minutes=row["horizon_minutes"],
            )
        )

    return ForecastTimelineOut(
        symbol=symbol,
        forecast_type=forecast_type,
        start_date=start_date,
        end_date=now,
        snapshots_count=len(snapshots),
        snapshots=snapshots,
    )


@app.get("/nfl/events/{event_id}/impact", response_model=EventImpactOut)
def get_event_impact(
    event_id: UUID,
    symbol: str = Query(..., description="Team symbol (e.g., 'NFL:DAL_COWBOYS')"),
) -> EventImpactOut:
    """
    Analyze the impact of a specific event on team forecasts.

    Shows:
    - Forecast value before and after the event
    - Change in forecast (positive = good news, negative = bad news)
    - Similar historical events and their average impact
    - Next game context

    **Example:**
    ```
    GET /nfl/events/123e4567-e89b-12d3-a456-426614174000/impact?symbol=NFL:DAL_COWBOYS
    ```

    **Response:**
    ```json
    {
      "event_id": "123e4567-e89b-12d3-a456-426614174000",
      "event_title": "Dak Prescott injury update: expected to play Sunday",
      "event_timestamp": "2025-12-10T14:23:00Z",
      "symbol": "NFL:DAL_COWBOYS",
      "forecast_before": 0.52,
      "forecast_after": 0.58,
      "forecast_change": 0.06,
      "similar_events_count": 42,
      "historical_impact_avg": 0.05,
      "next_game_date": "2025-12-15T18:00:00Z",
      "days_until_game": 5.3
    }
    ```

    **Use case:** Event detail page showing how news affected team's win probability
    """
    # Get event details
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT title, timestamp
                FROM events
                WHERE id = %s
                """,
                (event_id,),
            )
            event = cur.fetchone()

            if not event:
                raise HTTPException(status_code=404, detail="Event not found")

    event_timestamp = event["timestamp"]
    event_title = event["title"]

    # Get forecast snapshot for this event
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    forecast_value,
                    confidence,
                    sample_size,
                    target_date,
                    horizon_minutes
                FROM forecast_snapshots
                WHERE symbol = %s
                  AND event_id = %s
                  AND forecast_type = 'win_probability'
                ORDER BY snapshot_at DESC
                LIMIT 1
                """,
                (symbol, event_id),
            )
            snapshot = cur.fetchone()

    if not snapshot:
        # Event hasn't been processed yet - compute on the fly
        from models.nfl_event_forecaster import forecast_nfl_event

        result = forecast_nfl_event(
            event_id=event_id,
            team_symbol=symbol,
            event_timestamp=event_timestamp,
        )

        forecast_after = result.win_probability
        target_date = result.next_game_date
        days_until = result.days_until_game
        similar_events_count = result.similar_events_found
    else:
        forecast_after = float(snapshot["forecast_value"])
        target_date = snapshot["target_date"]
        days_until = snapshot["horizon_minutes"] / 1440.0 if snapshot["horizon_minutes"] else None
        similar_events_count = snapshot["sample_size"] or 0

    # Get forecast before event (most recent snapshot before event timestamp)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT forecast_value
                FROM forecast_snapshots
                WHERE symbol = %s
                  AND forecast_type = 'win_probability'
                  AND snapshot_at < %s
                ORDER BY snapshot_at DESC
                LIMIT 1
                """,
                (symbol, event_timestamp),
            )
            before = cur.fetchone()

    forecast_before = float(before["forecast_value"]) if before else None
    forecast_change = (forecast_after - forecast_before) if (forecast_before is not None and forecast_after is not None) else None

    # Calculate historical impact average (from similar events)
    # This would require additional queries to get historical event outcomes
    # For now, we'll use a placeholder based on sample size
    historical_impact_avg = forecast_change  # Simplified - could be more sophisticated

    return EventImpactOut(
        event_id=str(event_id),
        event_title=event_title,
        event_timestamp=event_timestamp,
        symbol=symbol,
        forecast_before=forecast_before,
        forecast_after=forecast_after,
        forecast_change=forecast_change,
        similar_events_count=similar_events_count,
        historical_impact_avg=historical_impact_avg,
        next_game_date=target_date,
        days_until_game=days_until,
    )
