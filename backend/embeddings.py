# backend/embeddings.py
import os
import hashlib
import time
from typing import List

from openai import OpenAI
from openai import RateLimitError, APIError, APITimeoutError

EMBEDDING_DIM = 3072
OPENAI_MODEL = "text-embedding-3-large"
OPENAI_TIMEOUT = float(os.getenv("OPENAI_EMBED_TIMEOUT", "15.0"))
MAX_EMBED_RETRIES = int(os.getenv("MAX_EMBED_RETRIES", "3"))

_client: OpenAI | None = None


def _get_client() -> OpenAI | None:
    global _client
    if _client is not None:
        return _client

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None

    _client = OpenAI(api_key=key, timeout=OPENAI_TIMEOUT)
    return _client


def _local_stub_embedding(text: str) -> List[float]:
    """
    Deterministic local embedding:
    - No network calls
    - Always length 1536
    - Same text -> same vector
    """
    text = " ".join(text.split()).strip()
    if not text:
        text = "EMPTY"

    h = hashlib.sha256(text.encode("utf-8")).digest()
    base = [b / 255.0 for b in h]  # 32 floats
    repeats = EMBEDDING_DIM // len(base) + 1
    return (base * repeats)[:EMBEDDING_DIM]


def embed_text(text: str) -> List[float]:
    """
    Hybrid embedding with retry logic:
    - Try OpenAI embeddings first (with retries + exponential backoff)
    - On persistent failure, fall back to local stub
    """
    text = " ".join(text.split()).strip()
    if not text:
        raise ValueError("Cannot embed empty text")

    client = _get_client()
    if client is None:
        print("[embeddings] No OPENAI_API_KEY found — using local stub.")
        return _local_stub_embedding(text)

    last_error: Exception | None = None

    for attempt in range(MAX_EMBED_RETRIES):
        try:
            resp = client.embeddings.create(
                model=OPENAI_MODEL,
                input=text,
            )
            print("[embeddings] OpenAI embed OK → using real embedding.")
            return resp.data[0].embedding

        except RateLimitError as e:
            last_error = e
            delay = 1.0 * (2 ** attempt)
            print(f"[embeddings] Rate limit ({e}); retrying in {delay:.1f}s...")
            time.sleep(delay)

        except APITimeoutError as e:
            last_error = e
            delay = 1.0 * (2 ** attempt)
            print(f"[embeddings] Timeout ({e}); retrying in {delay:.1f}s...")
            time.sleep(delay)

        except APIError as e:
            last_error = e
            if attempt < MAX_EMBED_RETRIES - 1:
                delay = 1.0 * (2 ** attempt)
                print(f"[embeddings] API error ({e}); retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                print(f"[embeddings] API error after retries: {e}")

        except Exception as e:
            last_error = e
            print(f"[embeddings] Unknown embedding error: {e}")
            break

    print(f"[embeddings] Falling back to local stub after failed attempts. Last error: {last_error}")
    return _local_stub_embedding(text)
