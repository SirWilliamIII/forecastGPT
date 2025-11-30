import os
from typing import List

from openai import OpenAI

# Reads OPENAI_API_KEY from env
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EMBEDDING_MODEL = "text-embedding-3-small"  # 1536-dim


def embed_text(text: str) -> List[float]:
    """
    Return a 1536-d embedding for the given text.
    """
    if not text:
        raise ValueError("Cannot embed empty text")

    # Normalize a bit
    text = " ".join(text.split())

    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return resp.data[0].embedding


