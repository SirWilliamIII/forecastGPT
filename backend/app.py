# backend/app.py

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg import sql
from dotenv import load_dotenv

from db import get_conn, close_pool
from embeddings import embed_text
from apscheduler.schedulers.background import BackgroundScheduler
from utils.url_utils import canonicalize_url

from models.naive_asset_forecaster import (
    forecast_asset as naive_forecast_asset,
    ForecastResult,
)
from models.event_return_forecaster import (
    forecast_event_return,
    EventReturnForecastResult,
)

# ---------------------------------------------------------------------
# Env + FastAPI init
# ---------------------------------------------------------------------

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = FastAPI(title="BloombergGPT Semantic Backend")

# Background scheduler for periodic ingestion
scheduler = BackgroundScheduler()


def run_rss_ingest():
    """Background job to ingest RSS feeds."""
    try:
        from ingest.rss_ingest import main as ingest_main
        print("[scheduler] Running RSS ingestion...")
        ingest_main()
        print("[scheduler] RSS ingestion complete.")
    except Exception as e:
        print(f"[scheduler] RSS ingestion error: {e}")


def run_crypto_backfill():
    """Background job to backfill crypto prices."""
    try:
        from ingest.backfill_crypto_returns import main as backfill_main
        print("[scheduler] Running crypto backfill...")
        backfill_main()
        print("[scheduler] Crypto backfill complete.")
    except Exception as e:
        print(f"[scheduler] Crypto backfill error: {e}")


@app.on_event("startup")
def startup_event():
    """Run ingestion on startup and schedule periodic jobs."""
    # Run immediately on startup
    run_rss_ingest()
    run_crypto_backfill()
    
    # Schedule RSS every hour, crypto daily
    scheduler.add_job(run_rss_ingest, "interval", hours=1, id="rss_ingest")
    scheduler.add_job(run_crypto_backfill, "interval", hours=24, id="crypto_backfill")
    scheduler.start()
    print("[scheduler] Started background ingestion scheduler (RSS: hourly, crypto: daily).")


@app.on_event("shutdown")
def shutdown_event():
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
        description="Optional manual embedding override; if omitted, backend generates one.",
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
                cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                row = cur.fetchone()
                if not row:
                    pgvector_status = "not_installed"
    except Exception:
        pgvector_status = "error"

    overall = "healthy" if db_status == "ok" and pgvector_status == "ok" else "unhealthy"

    return HealthCheck(status=overall, database=db_status, pgvector=pgvector_status)


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
    limit: int = Query(default=50, ge=1, le=200),
    source: Optional[str] = Query(default=None),
) -> List[EventSummary]:
    """
    Fetch recent events, optionally filtered by source.
    Returns newest first.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            if source is not None:
                cur.execute(
                    """
                    SELECT id, timestamp, source, url, title, summary, categories, tags
                    FROM events
                    WHERE source = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (source, int(limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT id, timestamp, source, url, title, summary, categories, tags
                    FROM events
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (int(limit),),
                )
            rows = cur.fetchall()

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
def get_similar_events(event_id: UUID, limit: int = 10) -> Dict[str, Any]:
    """
    Return nearest neighbors in embedding space for a given event_id.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Fetch anchor embedding
            cur.execute(
                "SELECT embed FROM events WHERE id = %s",
                (event_id,),
            )
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Event not found or has no embedding",
                )

            row_dict = dict(row)
            if row_dict["embed"] is None:
                raise HTTPException(
                    status_code=404,
                    detail="Event not found or has no embedding",
                )

            anchor_embed = row_dict["embed"]

            # Find neighbors
            cur.execute(
                """
                SELECT
                    id,
                    timestamp,
                    source,
                    url,
                    raw_text,
                    categories,
                    tags,
                    embed <-> %s::vector AS distance
                FROM events
                WHERE id <> %s
                ORDER BY embed <-> %s::vector
                LIMIT %s
                """,
                (anchor_embed, event_id, anchor_embed, limit),
            )

            rows = cur.fetchall()

    neighbors: List[Neighbor] = []
    for r in rows:
        rd: Dict[str, Any] = dict(r)
        neighbors.append(
            Neighbor(
                id=str(rd["id"]),
                timestamp=rd["timestamp"],
                source=rd["source"],
                url=rd["url"],
                raw_text=rd["raw_text"],
                categories=rd["categories"] or [],
                tags=rd["tags"] or [],
                distance=float(rd["distance"]),
            )
        )

    return {"event_id": str(event_id), "neighbors": neighbors}


# ---------------------------------------------------------------------
# Asset-level naive forecaster
# ---------------------------------------------------------------------


@app.get("/forecast/asset", response_model=AssetForecastOut)
def forecast_asset_endpoint(
    symbol: str,
    horizon_minutes: int = 1440,
    lookback_days: int = 60,
) -> AssetForecastOut:
    """
    Naive numeric forecaster for a given asset symbol.

    Example:
      GET /forecast/asset?symbol=BTC-USD&horizon_minutes=1440
    """
    as_of = datetime.now(tz=timezone.utc)

    result: ForecastResult = naive_forecast_asset(
        symbol=symbol,
        as_of=as_of,
        horizon_minutes=horizon_minutes,
        lookback_days=lookback_days,
    )

    return AssetForecastOut(**result.to_dict())


# ---------------------------------------------------------------------
# Event-conditioned (semantic) forecaster
# ---------------------------------------------------------------------


@app.get("/forecast/event/{event_id}", response_model=EventReturnForecastOut)
def forecast_event_endpoint(
    event_id: UUID,
    symbol: str,
    horizon_minutes: int = 1440,
    k_neighbors: int = 25,
    lookback_days: int = 365,
    price_window_minutes: int = 60,
    alpha: float = 0.5,
):
    """
    Phase 1 event-based forecaster.

    Given a stored event_id and an asset symbol/horizon, this:
      - finds semantically similar past events,
      - looks up realized returns around those events,
      - computes a distance-weighted forecast.

    If there's no data, EventReturnForecastResult will return neutral-ish stats.
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
# LLM-powered analysis endpoints
# ---------------------------------------------------------------------


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


@app.get("/analyze/event/{event_id}", response_model=EventAnalysisOut)
def analyze_event_endpoint(
    event_id: UUID,
    symbol: str = "BTC-USD",
    provider: str = "claude",
) -> EventAnalysisOut:
    """
    Analyze an event for market impact using LLM.

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

