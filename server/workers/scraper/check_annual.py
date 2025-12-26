#!/usr/bin/env python3
"""Check annual summaries."""
import asyncio
import asyncpg
import os

async def main():
    conn = await asyncpg.connect(dsn=os.environ['DATABASE_URL'])
    rows = await conn.fetch("""
        SELECT id, city_id, summary_type, status, is_stale 
        FROM summaries 
        WHERE summary_type = 'annual'
    """)
    for row in rows:
        print(dict(row))
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())

