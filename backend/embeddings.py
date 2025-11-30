import os
import hashlib
from typing import List

from openai import OpenAI
from openai import RateLimitError, APIError


EMBEDDING_DIM = 1536
OPENAI_MODEL = "text-embedding-3-small"


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
    Hybrid embedding:
    - Try OpenAI embeddings first
    - On any failure (429, quota, network), fall back to local stub
    """
    text = " ".join(text.split()).strip()
    if not text:
        raise ValueError("Cannot embed empty text")

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("[embeddings] No OPENAI_API_KEY found — using local stub.")
        return _local_stub_embedding(text)

    client = OpenAI(api_key=key)

    try:
        resp = client.embeddings.create(
            model=OPENAI_MODEL,
            input=text,
        )
        print("[embeddings] OpenAI embed OK → using real embedding.")
        return resp.data[0].embedding

    except RateLimitError:
        print("[embeddings] OpenAI rate limit/quota hit — falling back to local stub.")
        return _local_stub_embedding(text)

    except APIError as e:
        print(f"[embeddings] OpenAI API error: {e} — falling back to local stub.")
        return _local_stub_embedding(text)

    except Exception as e:
        print(f"[embeddings] Unknown embedding error: {e} — falling back to local stub.")
        return _local_stub_embedding(text)
