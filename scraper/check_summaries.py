#!/usr/bin/env python3
"""Check existing quarterly/monthly/annual summaries."""
import asyncio
import asyncpg
import os

async def main():
    conn = await asyncpg.connect(dsn=os.environ['DATABASE_URL'])
    rows = await conn.fetch("""
        SELECT id, summary_type, period_start, status, summary_text IS NOT NULL as has_text 
        FROM summaries 
        WHERE summary_type IN ('quarterly', 'monthly', 'annual') 
        ORDER BY period_start DESC LIMIT 15
    """)
    for row in rows:
        print(dict(row))
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
