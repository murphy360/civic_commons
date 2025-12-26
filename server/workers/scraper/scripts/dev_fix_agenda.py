#!/usr/bin/env python3
import asyncio
import asyncpg
import os

async def fix():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        # Fix the Planning Commission agenda links
        # Document 1 should link to Event 1 (Nov 17), not Event 42
        await conn.execute('DELETE FROM event_documents WHERE document_id IN (1, 2)')
        await conn.execute("INSERT INTO event_documents (event_id, document_id, relationship) VALUES (1, 1, 'agenda')")
        await conn.execute("INSERT INTO event_documents (event_id, document_id, relationship) VALUES (1, 2, 'attachment')")
        print('Fixed Planning Commission document links')
        
        # Verify
        links = await conn.fetch("""
            SELECT ed.event_id, ed.document_id, ed.relationship, d.title, e.start_time 
            FROM event_documents ed 
            JOIN documents d ON ed.document_id = d.id 
            JOIN events e ON ed.event_id = e.id 
            WHERE d.id IN (1,2)
        """)
        for link in links:
            print(f'  Doc {link[1]} -> Event {link[0]} ({link[4].date()}) [{link[2]}]')
    await pool.close()

asyncio.run(fix())

