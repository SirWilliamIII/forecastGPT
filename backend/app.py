from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from psycopg import sql
from dotenv import load_dotenv

from db import get_conn
from embeddings import embed_text
from utils.url_utils import canonicalize_url  # <- make sure this exists


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = FastAPI(title="BloombergGPT Semantic Backend")


class EventIn(BaseModel):
    timestamp: datetime = Field(..., description="UTC timestamp of the event")
    source: str = Field(..., description="Canonical source name, e.g., 'wired_ai'")
    url: Optional[str] = Field(
        None, description="Canonicalized URL of the event (can be null for synthetic events)"
    )
    title: str = Field(..., description="Headline or title of the event")
    summary: str = Field(..., description="Short summary or description")
    raw_text: str = Field(..., description="Raw combined text (title + summary)")
    clean_text: Optional[str] = Field(
        None, description="Text fed into embeddings; defaults to raw_text if omitted"
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

