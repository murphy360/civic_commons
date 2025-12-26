#!/usr/bin/env python3
"""Link Kids Yoga Squirrel document to its events."""

import asyncio
import asyncpg
import os


async def link_yoga():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        # Document 9 is "Kids Yoga Squirrel January 2026"
        doc_id = 9
        
        # Get all Kids Yoga events
        events = await conn.fetch(
            """SELECT DISTINCT e.id, e.title 
               FROM events e 
               WHERE e.title ILIKE '%yoga%squirrel%'"""
        )
        
        print(f'Linking document {doc_id} to {len(events)} events:')
        
        for event in events:
            event_id = event[0]
            event_title = event[1]
            
            # Insert link
            await conn.execute(
                """
                INSERT INTO event_documents (event_id, document_id, relationship)
                VALUES ($1, $2, 'attachment')
                ON CONFLICT (event_id, document_id) DO NOTHING
                """,
                event_id,
                doc_id,
            )
            print(f'  Linked Event {event_id}: {event_title}')
        
        # Verify
        links = await conn.fetch(
            'SELECT event_id, document_id FROM event_documents WHERE document_id = $1',
            doc_id
        )
        print(f'\nDocument {doc_id} is now linked to {len(links)} events')
    
    await pool.close()


if __name__ == '__main__':
    asyncio.run(link_yoga())

