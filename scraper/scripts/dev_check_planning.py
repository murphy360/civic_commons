#!/usr/bin/env python3
import asyncio
import asyncpg
import os

async def check():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        # Check event dates for Planning Commission
        events = await conn.fetch("""
            SELECT id, title, start_time 
            FROM events 
            WHERE title ILIKE '%planning%commission%'
            ORDER BY start_time
        """)
        print('Planning Commission events:')
        for e in events:
            print(f'  Event {e[0]}: {e[1]} on {e[2]}')
    await pool.close()

asyncio.run(check())
