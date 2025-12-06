#!/usr/bin/env python3
"""Test vector similarity search using Weaviate."""

from db import get_conn
from vector_store import get_vector_store

vs = get_vector_store()

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute('SELECT id, title FROM events LIMIT 1')
    row = cur.fetchone()

    if not row:
        print("No events in database")
        exit(1)

    event_id = row['id']
    print(f"Testing event: {row['title']}")
    print(f"Event ID: {event_id}")
    print()

    # Get vector and search for similar events
    vector = vs.get_vector(event_id)
    if not vector:
        print("❌ No vector found for this event")
        exit(1)

    print(f"✓ Retrieved vector ({len(vector)} dimensions)")
    print()

    # Search for similar events
    results = vs.search(vector, limit=5, exclude_id=event_id)
    print(f"Found {len(results)} similar events:")

    for r in results:
        # Get event metadata from PostgreSQL
        cur.execute('SELECT title, source FROM events WHERE id = %s', (r.event_id,))
        event = cur.fetchone()
        if event:
            print(f"  - Distance: {r.distance:.4f}")
            print(f"    Source: {event['source']}")
            print(f"    Title: {event['title'][:80]}...")
            print()

print("✅ Vector search test complete!")
