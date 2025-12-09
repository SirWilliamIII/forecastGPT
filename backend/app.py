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
    RSS_INGEST_INTERVAL_HOURS,
    CRYPTO_BACKFILL_INTERVAL_HOURS,
    EQUITY_BACKFILL_INTERVAL_HOURS,
    NFL_ELO_BACKFILL_INTERVAL_HOURS,
    BAKER_PROJECTIONS_INTERVAL_HOURS,
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


def run_baker_projections() -> None:
    """Background job to ingest Baker NFL projections (win probabilities)."""
    try:
        from ingest.baker_projections import ingest_once

        print("[scheduler] Running Baker projections ingest...")
        ingest_once()
        print("[scheduler] Baker projections ingest complete.")
    except Exception as e:
        print(f"[scheduler] Baker projections error: {e}")


def run_all_ingestion_jobs() -> None:
    """Run all ingestion jobs sequentially in background thread."""
    try:
        print("[scheduler] Starting background ingestion...")
        run_rss_ingest()
        run_crypto_backfill()
        run_equity_backfill()
        run_nfl_elo_backfill()
        run_baker_projections()
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

    scheduler.start()
    print(
        "[scheduler] ✓ Started background scheduler "
        "(RSS/Baker: hourly, crypto/equity/NFL Elo: daily)"
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
    Numeric baseline forecaster for a given asset symbol.

    Example:
      GET /forecast/asset?symbol=BTC-USD&horizon_minutes=1440&lookback_days=60

    Validation:
      - horizon_minutes: 1 to 43200 (30 days)
      - lookback_days: 1 to 730 (2 years)
    """
    as_of = datetime.now(tz=timezone.utc)

    asset_res = forecast_asset(
        symbol=symbol,
        as_of=as_of,
        horizon_minutes=horizon_minutes,
        lookback_days=lookback_days,
    )

    regime_res = classify_regime(symbol, as_of)

    payload = asset_res.to_dict()
    payload["regime"] = regime_res.regime
    payload["regime_score"] = regime_res.score

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
