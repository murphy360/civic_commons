#!/usr/bin/env python3
import asyncio
import asyncpg
import os

async def check():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        events = await conn.fetch("""
            SELECT e.id, e.title, e.start_time, e.location, es.source_url, s.name as source_name
            FROM events e
            JOIN event_sources es ON e.id = es.event_id
            JOIN sources s ON es.source_id = s.id
            WHERE e.title ILIKE '%wellness%'
            ORDER BY e.start_time
        """)
        print(f'Found {len(events)} Wellness events:')
        for e in events:
            print(f'  Event {e["id"]}: {e["title"]}')
            print(f'    Date: {e["start_time"]}')
            print(f'    Location: {e["location"]}')
            print(f'    Source: {e["source_name"]}')
            print(f'    URL: {e["source_url"]}')
            print()
    await pool.close()

asyncio.run(check())
