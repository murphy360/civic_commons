#!/usr/bin/env python3
"""Check Kids Yoga Squirrel document and event association."""

import asyncio
import asyncpg
import os


async def check():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        # Find Kids Yoga documents
        docs = await conn.fetch(
            "SELECT id, title, source_url FROM documents WHERE title ILIKE '%yoga%' OR title ILIKE '%squirrel%'"
        )
        print('Documents matching yoga/squirrel:')
        for doc in docs:
            print(f'  Doc {doc[0]}: {doc[1]}')
            print(f'    URL: {doc[2]}')
        
        # Find Kids Yoga events (using event_sources junction table)
        events = await conn.fetch(
            """SELECT e.id, e.title, es.source_url 
               FROM events e 
               LEFT JOIN event_sources es ON e.id = es.event_id
               WHERE e.title ILIKE '%yoga%' OR e.title ILIKE '%squirrel%'"""
        )
        print('\nEvents matching yoga/squirrel:')
        for ev in events:
            print(f'  Event {ev[0]}: {ev[1]}')
            print(f'    URL: {ev[2]}')
        
        # Check event_documents table
        links = await conn.fetch('SELECT event_id, document_id, relationship FROM event_documents')
        print(f'\nTotal event-document links: {len(links)}')
        for link in links:
            print(f'  Event {link[0]} <-> Doc {link[1]} ({link[2]})')
    await pool.close()


if __name__ == '__main__':
    asyncio.run(check())
