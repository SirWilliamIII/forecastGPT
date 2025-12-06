#!/usr/bin/env python3
"""Quick test to verify Weaviate connection."""

import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 70)
print("Weaviate Connection Test")
print("=" * 70)
print()

# Check environment variables
weaviate_url = os.getenv("WEAVIATE_URL")
weaviate_api_key = os.getenv("WEAVIATE_API_KEY")
weaviate_collection = os.getenv("WEAVIATE_COLLECTION", "forecaster")

print(f"WEAVIATE_URL: {weaviate_url}")
print(f"WEAVIATE_API_KEY: {'*' * 20 if weaviate_api_key else 'NOT SET'}")
print(f"WEAVIATE_COLLECTION: {weaviate_collection}")
print()

if not weaviate_url or not weaviate_api_key:
    print("❌ Weaviate not configured - will fall back to PostgreSQL")
    exit(0)

# Try connecting
print("🔌 Connecting to Weaviate...")
try:
    from vector_store import WeaviateVectorStore

    vs = WeaviateVectorStore()
    print("✅ Connected successfully!")
    print()

    # Try counting vectors (doesn't need PostgreSQL)
    print("📊 Checking vector count...")
    count = vs.count()
    print(f"✅ Found {count} vectors in Weaviate collection '{weaviate_collection}'")
    print()

    print("=" * 70)
    print("✅ Weaviate is ready to use!")
    print("=" * 70)

except Exception as e:
    print(f"❌ Connection failed: {e}")
    print()
    import traceback
    traceback.print_exc()
    exit(1)
