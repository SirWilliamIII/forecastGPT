#!/usr/bin/env python3
"""Test Weaviate vector search - find an event that exists in Weaviate."""

from db import get_conn
from vector_store import get_vector_store
import weaviate

vs = get_vector_store()

print(f"Using vector store: {type(vs).__name__}")
print()

# Get a random event ID from Weaviate
client = weaviate.connect_to_weaviate_cloud(
    cluster_url="https://hxcwmsuryamo3nvjmuwng.c0.us-east-1.aws.weaviate.cloud",
    auth_credentials=weaviate.auth.AuthApiKey("MkZ1eHVOSFZlZDVpVEdEUF9PM0tkWFRYQjhZbHg4cnBFWG56N1RmbVlEY0JVME96UHljTTQ4VmxqWVJNPV92MjAw"),
)

collection = client.collections.get("forecaster")
result = collection.query.fetch_objects(limit=1)

if not result.objects:
    print("No objects in Weaviate collection")
    client.close()
    exit(1)

event_id = result.objects[0].uuid
print(f"Testing with event from Weaviate: {event_id}")

client.close()

# Now test with this event
with get_conn() as conn:
    cur = conn.cursor()
    cur.execute('SELECT id, title, source FROM events WHERE id = %s', (event_id,))
    row = cur.fetchone()

    if not row:
        print(f"Event {event_id} not found in PostgreSQL")
        exit(1)

    print(f"Event title: {row['title']}")
    print(f"Event source: {row['source']}")
    print()

    # Get vector
    vector = vs.get_vector(event_id)
    if not vector:
        print("❌ No vector found for this event")
        exit(1)

    print(f"✓ Retrieved vector ({len(vector)} dimensions)")
    print()

    # Search for similar events
    results = vs.search(vector, limit=5, exclude_id=event_id)
    print(f"Found {len(results)} similar events:")
    print()

    for i, r in enumerate(results, 1):
        # Get event metadata from PostgreSQL
        cur.execute('SELECT title, source FROM events WHERE id = %s', (r.event_id,))
        event = cur.fetchone()
        if event:
            print(f"{i}. Distance: {r.distance:.4f}")
            print(f"   Source: {event['source']}")
            print(f"   Title: {event['title'][:80]}")
            print()

print("✅ Weaviate vector search test complete!")
