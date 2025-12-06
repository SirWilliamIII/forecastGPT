"""
Vector store abstraction layer supporting multiple backends.

Supports:
- Weaviate (primary)
- PostgreSQL pgvector (fallback)

Configuration via environment variables:
- WEAVIATE_URL: Weaviate cluster URL
- WEAVIATE_API_KEY: Weaviate API key
- WEAVIATE_COLLECTION: Collection/class name (default: "forecaster")

If Weaviate is not configured, falls back to PostgreSQL pgvector.
"""

import os
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple
from uuid import UUID
from datetime import datetime

from dotenv import load_dotenv
from config import EMBEDDING_DIM

# Load environment variables from .env file
load_dotenv()


class VectorSearchResult:
    """Unified search result across vector store backends."""

    def __init__(
        self,
        event_id: str,
        distance: float,
        metadata: Optional[Dict] = None,
    ):
        self.event_id = event_id
        self.distance = distance
        self.metadata = metadata or {}

    def __repr__(self):
        return f"VectorSearchResult(event_id={self.event_id}, distance={self.distance:.4f})"


class VectorStore(ABC):
    """Abstract base class for vector storage backends."""

    @abstractmethod
    def insert_batch(
        self,
        vectors: List[Tuple[UUID, List[float], Dict]],
    ) -> int:
        """
        Insert multiple vectors in batch.

        Args:
            vectors: List of (event_id, vector, metadata) tuples
                metadata: {timestamp, source, categories, tags}

        Returns:
            Number of successfully inserted vectors
        """
        pass

    @abstractmethod
    def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        exclude_id: Optional[UUID] = None,
    ) -> List[VectorSearchResult]:
        """
        Search for nearest neighbors.

        Args:
            query_vector: Query embedding vector
            limit: Maximum results to return
            exclude_id: Optional event ID to exclude from results

        Returns:
            List of VectorSearchResult objects
        """
        pass

    @abstractmethod
    def get_vector(self, event_id: UUID) -> Optional[List[float]]:
        """
        Get vector for a specific event.

        Args:
            event_id: Event UUID

        Returns:
            Vector if found, None otherwise
        """
        pass

    @abstractmethod
    def delete(self, event_id: UUID) -> bool:
        """
        Delete a vector.

        Args:
            event_id: Event UUID

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def count(self) -> int:
        """Get total number of vectors stored."""
        pass


class WeaviateVectorStore(VectorStore):
    """Weaviate cloud vector store implementation."""

    def __init__(self):
        import weaviate
        from weaviate.classes.init import Auth

        self.url = os.getenv("WEAVIATE_URL")
        self.api_key = os.getenv("WEAVIATE_API_KEY")
        self.collection_name = os.getenv("WEAVIATE_COLLECTION", "forecaster")

        if not self.url:
            raise ValueError("WEAVIATE_URL environment variable not set")
        if not self.api_key:
            raise ValueError("WEAVIATE_API_KEY environment variable not set")

        # Add https:// if not present
        if not self.url.startswith("http"):
            self.url = f"https://{self.url}"

        print(f"[vector_store] Connecting to Weaviate: {self.url}")
        print(f"[vector_store] Collection: {self.collection_name}")

        self.client = weaviate.connect_to_weaviate_cloud(
            cluster_url=self.url,
            auth_credentials=Auth.api_key(self.api_key),
        )

        # Ensure collection exists
        self._ensure_collection()

    def _ensure_collection(self):
        """Ensure the Weaviate collection/class exists with proper schema."""
        from weaviate.classes.config import Configure, Property, DataType

        try:
            # Check if collection exists
            if self.client.collections.exists(self.collection_name):
                print(f"[vector_store] Collection '{self.collection_name}' exists")
                self.collection = self.client.collections.get(self.collection_name)
                return

            # Create collection
            print(f"[vector_store] Creating collection '{self.collection_name}'")
            self.collection = self.client.collections.create(
                name=self.collection_name,
                description="Event embeddings for semantic search and forecasting",
                vectorizer_config=Configure.Vectorizer.none(),  # We provide vectors
                properties=[
                    Property(
                        name="eventId",
                        data_type=DataType.TEXT,
                        description="UUID of the event in PostgreSQL",
                    ),
                    Property(
                        name="timestamp",
                        data_type=DataType.DATE,
                        description="Event timestamp",
                    ),
                    Property(
                        name="source",
                        data_type=DataType.TEXT,
                        description="RSS feed source",
                    ),
                    Property(
                        name="categories",
                        data_type=DataType.TEXT_ARRAY,
                        description="Event categories",
                    ),
                    Property(
                        name="tags",
                        data_type=DataType.TEXT_ARRAY,
                        description="Event tags",
                    ),
                ],
            )
            print(f"[vector_store] ✓ Created collection '{self.collection_name}'")

        except Exception as e:
            print(f"[vector_store] Error ensuring collection: {e}")
            raise

    def insert_batch(
        self,
        vectors: List[Tuple[UUID, List[float], Dict]],
    ) -> int:
        """Insert multiple vectors in batch."""
        if not vectors:
            return 0

        from weaviate.classes.data import DataObject

        try:
            objects = []
            for event_id, vector, metadata in vectors:
                # Weaviate expects RFC3339 format for dates
                timestamp = metadata.get("timestamp")
                if isinstance(timestamp, datetime):
                    timestamp = timestamp.isoformat()

                obj = DataObject(
                    properties={
                        "eventId": str(event_id),
                        "timestamp": timestamp,
                        "source": metadata.get("source", ""),
                        "categories": metadata.get("categories", []),
                        "tags": metadata.get("tags", []),
                    },
                    vector=vector,
                )
                objects.append(obj)

            # Batch insert
            self.collection = self.client.collections.get(self.collection_name)
            response = self.collection.data.insert_many(objects)

            # Check for errors
            if response.has_errors:
                errors = [str(e) for e in response.errors.values()]
                print(f"[vector_store] Batch insert errors: {errors[:3]}")
                return len(vectors) - len(response.errors)

            print(f"[vector_store] ✓ Inserted {len(vectors)} vectors to Weaviate")
            return len(vectors)

        except Exception as e:
            print(f"[vector_store] Error inserting batch: {e}")
            return 0

    def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        exclude_id: Optional[UUID] = None,
    ) -> List[VectorSearchResult]:
        """Search for nearest neighbors."""
        from weaviate.classes.query import Filter

        try:
            self.collection = self.client.collections.get(self.collection_name)

            # Build filter to exclude specific ID
            where_filter = None
            if exclude_id:
                where_filter = Filter.by_property("eventId").not_equal(str(exclude_id))

            # Near vector search
            response = self.collection.query.near_vector(
                near_vector=query_vector,
                limit=limit,
                return_metadata=["distance"],
                filters=where_filter,
            )

            results = []
            for obj in response.objects:
                results.append(
                    VectorSearchResult(
                        event_id=obj.properties.get("eventId"),
                        distance=obj.metadata.distance,
                        metadata={
                            "timestamp": obj.properties.get("timestamp"),
                            "source": obj.properties.get("source"),
                            "categories": obj.properties.get("categories", []),
                            "tags": obj.properties.get("tags", []),
                        },
                    )
                )

            return results

        except Exception as e:
            print(f"[vector_store] Error searching: {e}")
            return []

    def get_vector(self, event_id: UUID) -> Optional[List[float]]:
        """Get vector for a specific event."""
        from weaviate.classes.query import Filter

        try:
            self.collection = self.client.collections.get(self.collection_name)

            response = self.collection.query.fetch_objects(
                filters=Filter.by_property("eventId").equal(str(event_id)),
                include_vector=True,
                limit=1,
            )

            if response.objects:
                return response.objects[0].vector.get("default")

            return None

        except Exception as e:
            print(f"[vector_store] Error getting vector: {e}")
            return None

    def delete(self, event_id: UUID) -> bool:
        """Delete a vector."""
        from weaviate.classes.query import Filter

        try:
            self.collection = self.client.collections.get(self.collection_name)

            result = self.collection.data.delete_many(
                where=Filter.by_property("eventId").equal(str(event_id))
            )

            return result.successful > 0

        except Exception as e:
            print(f"[vector_store] Error deleting: {e}")
            return False

    def count(self) -> int:
        """Get total number of vectors stored."""
        try:
            self.collection = self.client.collections.get(self.collection_name)
            response = self.collection.aggregate.over_all(total_count=True)
            return response.total_count

        except Exception as e:
            print(f"[vector_store] Error counting: {e}")
            return 0

    def __del__(self):
        """Close Weaviate connection on cleanup."""
        try:
            if hasattr(self, "client"):
                self.client.close()
        except:
            pass


class PostgresVectorStore(VectorStore):
    """PostgreSQL pgvector fallback implementation."""

    def __init__(self):
        print("[vector_store] Using PostgreSQL pgvector (fallback)")

    def insert_batch(
        self,
        vectors: List[Tuple[UUID, List[float], Dict]],
    ) -> int:
        """Insert vectors into PostgreSQL events table."""
        from db import get_conn
        from psycopg import sql

        if not vectors:
            return 0

        inserted = 0
        with get_conn() as conn:
            with conn.cursor() as cur:
                for event_id, vector, metadata in vectors:
                    try:
                        # Update existing event with vector
                        embed_literal = "[" + ",".join(str(x) for x in vector) + "]"
                        cur.execute(
                            "UPDATE events SET embed = %s::vector WHERE id = %s",
                            (embed_literal, event_id),
                        )
                        inserted += 1
                    except Exception as e:
                        print(f"[vector_store] Error inserting {event_id}: {e}")

                conn.commit()

        print(f"[vector_store] ✓ Updated {inserted} vectors in PostgreSQL")
        return inserted

    def search(
        self,
        query_vector: List[float],
        limit: int = 10,
        exclude_id: Optional[UUID] = None,
    ) -> List[VectorSearchResult]:
        """Search using pgvector cosine distance."""
        import numpy as np
        from db import get_conn

        # Convert to numpy array if not already (pgvector adapter handles this)
        if not isinstance(query_vector, np.ndarray):
            query_vector = np.array(query_vector)

        with get_conn() as conn:
            with conn.cursor() as cur:
                if exclude_id:
                    cur.execute(
                        """
                        SELECT id, embed <-> %s AS distance
                        FROM events
                        WHERE id <> %s AND embed IS NOT NULL
                        ORDER BY embed <-> %s
                        LIMIT %s
                        """,
                        (query_vector, exclude_id, query_vector, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, embed <-> %s AS distance
                        FROM events
                        WHERE embed IS NOT NULL
                        ORDER BY embed <-> %s
                        LIMIT %s
                        """,
                        (query_vector, query_vector, limit),
                    )

                rows = cur.fetchall()

        results = []
        for row in rows:
            results.append(
                VectorSearchResult(
                    event_id=str(row["id"]),
                    distance=float(row["distance"]),
                )
            )

        return results

    def get_vector(self, event_id: UUID) -> Optional[List[float]]:
        """Get vector from PostgreSQL."""
        from db import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT embed FROM events WHERE id = %s", (event_id,))
                row = cur.fetchone()

                if row and row["embed"] is not None:
                    # pgvector adapter returns numpy array, convert to list
                    return row["embed"].tolist()

        return None

    def delete(self, event_id: UUID) -> bool:
        """Set vector to NULL in PostgreSQL."""
        from db import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE events SET embed = NULL WHERE id = %s", (event_id,)
                )
                conn.commit()
                return cur.rowcount > 0

    def count(self) -> int:
        """Count events with vectors."""
        from db import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM events WHERE embed IS NOT NULL")
                row = cur.fetchone()
                return int(row["count"]) if row else 0


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """
    Get the configured vector store instance.

    Returns Weaviate if configured, otherwise falls back to PostgreSQL.
    """
    global _vector_store

    if _vector_store is not None:
        return _vector_store

    # Try Weaviate first
    weaviate_url = os.getenv("WEAVIATE_URL")
    weaviate_api_key = os.getenv("WEAVIATE_API_KEY")

    if weaviate_url and weaviate_api_key:
        try:
            _vector_store = WeaviateVectorStore()
            print("[vector_store] ✓ Using Weaviate vector store")
            return _vector_store
        except Exception as e:
            print(f"[vector_store] ⚠️  Weaviate initialization failed: {e}")
            print("[vector_store] Falling back to PostgreSQL pgvector")

    # Fallback to PostgreSQL
    _vector_store = PostgresVectorStore()
    return _vector_store
