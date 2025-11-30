from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from psycopg import sql

from db import get_conn
from embeddings import embed_text
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY=os.getenv("OPENAI_API_KEY")

breakpoint()

app = FastAPI(title="BloombergGPT Semantic Backend")


class EventCreate(BaseModel):
    timestamp: datetime
    source: str
    url: Optional[str] = None
    raw_text: str
    clean_text: Optional[str] = None
    categories: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    embed: Optional[List[float]] = None  # optional manual override


class Neighbor(BaseModel):
    id: str
    timestamp: Optional[datetime]
    source: str
    url: Optional[str]
    raw_text: str
    categories: Optional[List[str]]
    tags: Optional[List[str]]
    distance: float


@app.post("/events")
def create_event(event: EventCreate):
    """
    Insert a new event row.
    If no embedding is provided, we generate one from clean_text or raw_text.
    """
    event_id = uuid4()

    # Pick which text to embed
    text_to_embed = event.clean_text or event.raw_text

    # Generate embedding if not provided
    if event.embed is not None:
        embed_vector = event.embed
    else:
        embed_vector = embed_text(text_to_embed)

    # pgvector literal format: [0.1,0.2,...]
    embed_literal = "[" + ",".join(str(x) for x in embed_vector) + "]"

    cols = [
        "id",
        "timestamp",
        "source",
        "url",
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
        event.url,
        event.raw_text,
        event.clean_text,
        event.categories,
        event.tags,
        embed_literal,
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("INSERT INTO events ({}) VALUES ({})").format(
                    sql.SQL(", ").join(sql.Identifier(col) for col in cols),
                    sql.SQL(", ").join(sql.Placeholder() * len(cols))
                ),
                values,
            )

    return {"id": str(event_id)}


@app.get("/events/{event_id}/similar")
def get_similar_events(event_id: UUID, limit: int = 10):
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
        row_dict: Dict[str, Any] = dict(r)
        neighbors.append(
            Neighbor(
                id=str(row_dict["id"]),
                timestamp=row_dict["timestamp"],
                source=row_dict["source"],
                url=row_dict["url"],
                raw_text=row_dict["raw_text"],
                categories=row_dict["categories"],
                tags=row_dict["tags"],
                distance=float(row_dict["distance"]),
            )
        )

    return {"event_id": str(event_id), "neighbors": neighbors}
