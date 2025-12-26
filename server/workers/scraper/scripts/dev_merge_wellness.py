#!/usr/bin/env python3
"""Merge duplicate Wellness Seminar events."""
import asyncio
import asyncpg
import os

async def merge():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        # Event 8 is the older one, Event 60 is newer
        # Move all event_sources from 60 to 8 (skip if already exists)
        await conn.execute("""
            INSERT INTO event_sources (event_id, source_id, source_url)
            SELECT 8, source_id, source_url FROM event_sources WHERE event_id = 60
            ON CONFLICT (event_id, source_id) DO NOTHING
        """)
        
        # Move any event_documents from 60 to 8 (skip if already exists)
        await conn.execute("""
            INSERT INTO event_documents (event_id, document_id, relationship)
            SELECT 8, document_id, relationship FROM event_documents WHERE event_id = 60
            ON CONFLICT (event_id, document_id) DO NOTHING
        """)
        
        # Delete event 60 references
        await conn.execute('DELETE FROM event_documents WHERE event_id = 60')
        await conn.execute('DELETE FROM event_sources WHERE event_id = 60')
        await conn.execute('DELETE FROM events WHERE id = 60')
        
        print('Merged Event 60 into Event 8')
        
        # Verify
        events = await conn.fetch("SELECT id, title FROM events WHERE title ILIKE '%wellness%'")
        print(f'Remaining Wellness events: {len(events)}')
        for e in events:
            print(f'  {e[0]}: {e[1]}')
    await pool.close()

asyncio.run(merge())

