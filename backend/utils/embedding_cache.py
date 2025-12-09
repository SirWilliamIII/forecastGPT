# backend/utils/embedding_cache.py
"""
Persistent cache for OpenAI embeddings to reduce API costs and latency.

The cache stores embeddings in a SQLite database, keyed by the SHA256 hash
of the input text. This allows:
- Avoiding duplicate API calls for the same text
- Faster ingestion on re-runs (e.g., RSS feeds with overlapping entries)
- Reduced OpenAI API costs

Thread-safe for concurrent access.
"""

import os
import sqlite3
import hashlib
import json
import threading
from typing import List, Optional


class EmbeddingCache:
    """Thread-safe persistent cache for embeddings."""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize embedding cache.

        Args:
            db_path: Path to SQLite database file. Defaults to backend/.cache/embeddings.db
        """
        if db_path is None:
            # Default to backend/.cache/embeddings.db
            backend_dir = os.path.dirname(os.path.dirname(__file__))
            cache_dir = os.path.join(backend_dir, ".cache")
            os.makedirs(cache_dir, exist_ok=True)
            db_path = os.path.join(cache_dir, "embeddings.db")

        self.db_path = db_path
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        """Create embeddings table if it doesn't exist."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS embeddings (
                        text_hash TEXT PRIMARY KEY,
                        embedding TEXT NOT NULL,
                        dimension INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        hit_count INTEGER DEFAULT 0
                    )
                """)
                # Index for cache statistics
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_embeddings_created
                    ON embeddings (created_at DESC)
                """)
                conn.commit()
            finally:
                conn.close()

    def _hash_text(self, text: str) -> str:
        """Generate SHA256 hash of text for cache key."""
        # Normalize whitespace before hashing for better cache hit rate
        normalized = " ".join(text.split()).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get(self, text: str) -> Optional[List[float]]:
        """
        Get cached embedding for text.

        Args:
            text: Text to look up

        Returns:
            List of floats (embedding vector) if cached, None otherwise
        """
        text_hash = self._hash_text(text)

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    """
                    SELECT embedding FROM embeddings WHERE text_hash = ?
                    """,
                    (text_hash,)
                )
                row = cursor.fetchone()

                if row:
                    # Increment hit counter
                    conn.execute(
                        """
                        UPDATE embeddings SET hit_count = hit_count + 1
                        WHERE text_hash = ?
                        """,
                        (text_hash,)
                    )
                    conn.commit()

                    # Deserialize JSON array
                    return json.loads(row[0])

                return None
            finally:
                conn.close()

    def set(self, text: str, embedding: List[float]):
        """
        Cache an embedding.

        Args:
            text: Original text
            embedding: Embedding vector
        """
        text_hash = self._hash_text(text)
        dimension = len(embedding)
        embedding_json = json.dumps(embedding)

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO embeddings (text_hash, embedding, dimension, hit_count)
                    VALUES (?, ?, ?, COALESCE((SELECT hit_count FROM embeddings WHERE text_hash = ?), 0))
                    """,
                    (text_hash, embedding_json, dimension, text_hash)
                )
                conn.commit()
            finally:
                conn.close()

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache size, hit count, etc.
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total_entries,
                        SUM(hit_count) as total_hits,
                        AVG(hit_count) as avg_hits_per_entry,
                        MAX(dimension) as embedding_dimension
                    FROM embeddings
                """)
                row = cursor.fetchone()

                if row:
                    return {
                        "total_entries": row[0] or 0,
                        "total_hits": row[1] or 0,
                        "avg_hits_per_entry": row[2] or 0.0,
                        "embedding_dimension": row[3] or 0,
                        "db_path": self.db_path,
                    }
                return {"total_entries": 0}
            finally:
                conn.close()

    def clear(self):
        """Clear all cached embeddings."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("DELETE FROM embeddings")
                conn.commit()
            finally:
                conn.close()


# Global cache instance
_cache: Optional[EmbeddingCache] = None


def get_cache() -> EmbeddingCache:
    """Get or create global cache instance."""
    global _cache
    if _cache is None:
        _cache = EmbeddingCache()
    return _cache


if __name__ == "__main__":
    # Test the cache
    print("Testing embedding cache...")

    cache = EmbeddingCache()

    # Test set and get
    test_text = "Bitcoin surges to new all-time high"
    test_embedding = [0.1, 0.2, 0.3] * 100  # Mock 300-dim vector

    print(f"\nStoring embedding for: {test_text}")
    cache.set(test_text, test_embedding)

    print("Retrieving from cache...")
    cached = cache.get(test_text)

    if cached == test_embedding:
        print("✓ Cache hit successful!")
    else:
        print("✗ Cache miss or mismatch")

    # Test cache miss
    print("\nTesting cache miss...")
    result = cache.get("This text is not cached")
    print(f"✓ Cache miss returns None: {result is None}")

    # Test stats
    print("\nCache statistics:")
    stats = cache.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Test normalization (whitespace handling)
    print("\nTesting whitespace normalization...")
    cache.set("Bitcoin  surges   to new   high", test_embedding)
    cached2 = cache.get("Bitcoin surges to new high")
    print(f"✓ Whitespace normalized: {cached2 == test_embedding}")
