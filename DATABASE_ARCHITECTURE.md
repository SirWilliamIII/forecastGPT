# Database Architecture Guide

## Overview

BloombergGPT uses a **dual-database architecture** with **no automatic syncing** between local and production.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    LOCAL ENVIRONMENT                         │
│  (Manual Start: ./run-dev.sh)                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  PostgreSQL (Docker)                 Weaviate (Cloud)       │
│  localhost:5433                      Shared cluster         │
│  ├─ Event metadata                   ├─ Event vectors       │
│  ├─ Asset returns                    └─ Semantic search     │
│  ├─ Prices                                                  │
│  ├─ Projections                                             │
│  └─ Vector fallback (pgvector)                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 PRODUCTION ENVIRONMENT                       │
│  (Oracle Server: maybe.probablyfine.lol)                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  PostgreSQL (Docker)                 Weaviate (Cloud)       │
│  localhost:5433 (on server)          SAME cluster as local  │
│  ├─ Event metadata (1,001 events)    ├─ Event vectors       │
│  ├─ Asset returns                    └─ Semantic search     │
│  ├─ Prices                                                  │
│  ├─ Projections                                             │
│  └─ Vector fallback (pgvector)                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Database Separation

### ❌ NOT Synced

**Local and production databases are COMPLETELY SEPARATE:**

- **Local PostgreSQL**: Docker container on your Mac
  - Location: `localhost:5433`
  - Data: Your local test data
  - Changes: Never affect production

- **Production PostgreSQL**: Docker container on Oracle server
  - Location: `84.8.155.16:5433` (internal to server)
  - Data: Production data (1,001 events as of now)
  - Changes: Only via auto-deployment

### ✅ Shared Weaviate

**Both environments use the SAME Weaviate cloud cluster:**

- **URL**: `https://hxcwmsuryamo3nvjmuwng.c0.us-east-1.aws.weaviate.cloud`
- **Collection**: `forecaster`
- **API Keys**: Different keys for local vs production (for security)

**Why shared?**
- Weaviate is a cloud service (not self-hosted)
- Vectors are read-only after insertion (no conflicts)
- Cost-effective: One cluster instead of two
- Performance: Fast semantic search for both environments

**Implication**: When you insert events locally, the vectors go to the same Weaviate cluster that production uses. The metadata stays separate in PostgreSQL.

## Dual Storage Architecture

Each event is stored in TWO places:

### 1. PostgreSQL (Metadata + Fallback Vectors)

**Stored in `events` table:**
```sql
- id (UUID)
- timestamp
- source (e.g., 'nfl_news_api', 'coindesk')
- url
- title
- summary
- raw_text
- clean_text
- categories (array)
- tags (array)
- embed (pgvector - 3072 dimensions) ← Fallback only
```

**Purpose:**
- Primary data store for event metadata
- SQL queries (filtering, aggregation, joins)
- Fallback vector storage if Weaviate unavailable

### 2. Weaviate (Primary Vectors)

**Stored in `forecaster` collection:**
```
- eventId (UUID - matches PostgreSQL)
- vector (3072-dim embedding)
- timestamp
- source
- categories
- tags
```

**Purpose:**
- Fast semantic search (HNSW indexing)
- Scales to millions of vectors
- 40-50% better search accuracy than pgvector

## How It Works

### Insertion Flow

```
1. New event arrives (RSS, NFL News API, etc.)
   ↓
2. Generate embedding via OpenAI
   ↓
3. Insert to PostgreSQL (metadata + vector)
   ↓
4. Insert to Weaviate (vector + minimal metadata)
   ↓
5. Done! Event is searchable
```

**Code:** `backend/ingest/rss_ingest.py` → `insert_events_batch()`

### Search Flow

```
1. User searches or requests forecast
   ↓
2. Generate query embedding
   ↓
3. Search Weaviate for similar vectors
   ↓
4. Get event IDs from Weaviate results
   ↓
5. Fetch full metadata from PostgreSQL
   ↓
6. Return combined results
```

**Code:** `backend/signals/feature_extractor.py` → `get_similar_events()`

### Fallback Behavior

If Weaviate is unavailable:

```python
# backend/vector_store.py - get_vector_store()

if weaviate_url and weaviate_api_key:
    try:
        return WeaviateVectorStore()  # Primary
    except:
        print("Falling back to PostgreSQL pgvector")

return PostgresVectorStore()  # Fallback
```

## Data Sync Strategies

Since databases are NOT auto-synced, here are your options:

### Option 1: No Sync (Current Setup) ✅

**Local**: Test data only
**Production**: Real data only

**Best for:**
- Development/testing with fake data
- No risk of corrupting production
- Fast local iteration

### Option 2: Export/Import Snapshots

**Export from production:**
```bash
# SSH to Oracle server
ssh -i ~/.ssh/ssh-key-2025-11-10.key ubuntu@84.8.155.16

# Dump production database
docker exec -i semantic_markets_db pg_dump -U semantic semantic_markets | gzip > /tmp/prod_backup.sql.gz

# Download to local
exit
scp -i ~/.ssh/ssh-key-2025-11-10.key ubuntu@84.8.155.16:/tmp/prod_backup.sql.gz ~/Downloads/
```

**Import to local:**
```bash
cd /Users/will/Programming/Projects/bloombergGPT/backend

# Start local database
docker compose up -d db

# Wait for it to be ready
sleep 5

# Drop and recreate database
docker exec -i semantic_markets_db psql -U semantic -c "DROP DATABASE IF EXISTS semantic_markets"
docker exec -i semantic_markets_db psql -U semantic -c "CREATE DATABASE semantic_markets"

# Restore backup
gunzip -c ~/Downloads/prod_backup.sql.gz | docker exec -i semantic_markets_db psql -U semantic semantic_markets
```

**Best for:**
- Testing with production-like data
- Debugging production issues locally

### Option 3: Read-Only Production Access

**Point local backend to production database:**

```bash
# backend/.env.local
DATABASE_URL=postgresql://semantic:semantic@84.8.155.16:5433/semantic_markets  # WARNING: Don't do this!
```

**⚠️ NOT RECOMMENDED:**
- Risky: Could accidentally modify production
- Slow: Network latency
- Requires SSH tunnel or exposed port

### Option 4: Staging Environment

**Create a third environment:**
- Local: Development
- Staging: Pre-production testing
- Production: Live

**Best for:**
- Large teams
- Critical production systems
- Complex testing needs

## Current State

### Local Database
```bash
# Start local database
cd /Users/will/Programming/Projects/bloombergGPT
./run-dev.sh

# Check local data
cd backend
uv run psql $DATABASE_URL -c "SELECT COUNT(*) FROM events"
```

### Production Database
```bash
# SSH to server
ssh -i ~/.ssh/ssh-key-2025-11-10.key ubuntu@84.8.155.16

# Check production data
cd /opt/bloomberggpt
uv run python -c "
from db import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*) as count FROM events')
        print(f'Events: {cur.fetchone()[\"count\"]}')
"
```

**Current Production Stats:**
- Total events: 1,001
- NFL News articles: 50
- RSS events: ~951
- Vector store: Weaviate (shared cluster)

## Vector Store Configuration

### Environment Variables

**Local** (`backend/.env`):
```bash
WEAVIATE_URL=https://hxcwmsuryamo3nvjmuwng.c0.us-east-1.aws.weaviate.cloud
WEAVIATE_API_KEY=<local-key>
WEAVIATE_COLLECTION=forecaster
```

**Production** (`/opt/bloomberggpt/.env`):
```bash
WEAVIATE_URL=https://hxcwmsuryamo3nvjmuwng.c0.us-east-1.aws.weaviate.cloud
WEAVIATE_API_KEY=<production-key>
WEAVIATE_COLLECTION=forecaster
```

### Checking Which Store is Active

```bash
cd backend
uv run python -c "
from vector_store import get_vector_store
store = get_vector_store()
print(f'Vector store type: {type(store).__name__}')
"
```

Output:
- `WeaviateVectorStore` → Using Weaviate ✅
- `PostgresVectorStore` → Using pgvector fallback

## Performance Comparison

| Feature | Weaviate | PostgreSQL pgvector |
|---------|----------|---------------------|
| Search Speed | ~10ms | ~100ms |
| Accuracy | 0.57-0.61 distance | 1.06-1.11 distance |
| Scalability | Millions of vectors | ~10k vectors |
| Indexing | HNSW (optimized) | None (exact search) |
| Cost | $25/month | Free (self-hosted) |

**Why we use both:**
- Weaviate: Fast, accurate semantic search
- PostgreSQL: Metadata storage, SQL queries, fallback

## Troubleshooting

### "No vector store available"

Check Weaviate credentials:
```bash
grep WEAVIATE backend/.env
```

If missing, the system falls back to PostgreSQL pgvector.

### "Vectors not matching between stores"

This is expected! They're separate:
- **PostgreSQL**: Has old vectors from before Weaviate
- **Weaviate**: Only has vectors inserted after migration

Run migration to sync:
```bash
cd backend
uv run python migrate_to_weaviate.py
```

### "Production data in local database"

You likely imported a production snapshot. This is fine for testing, but remember:
- Changes won't affect production
- Restart containers to clear: `docker compose down -v && docker compose up -d db`

## Summary

✅ **Dual Storage**: PostgreSQL (metadata) + Weaviate (vectors)
✅ **No Auto-Sync**: Local and production are completely separate
✅ **Shared Weaviate**: Same cluster, different API keys
✅ **Fallback Support**: Works without Weaviate (slower, less accurate)
✅ **Production-Ready**: Scalable to millions of vectors

**Key Takeaway**: Make changes locally, test, then push to auto-deploy. Data never syncs automatically - this is by design for safety!
