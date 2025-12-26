#!/usr/bin/env python3
"""Check pending summaries by type."""
import asyncio
import asyncpg
import os

async def main():
    conn = await asyncpg.connect(dsn=os.environ['DATABASE_URL'])
    rows = await conn.fetch("""
        SELECT summary_type, COUNT(*) as cnt 
        FROM summaries 
        WHERE (is_stale = true OR status = 'pending')
        GROUP BY summary_type
        ORDER BY summary_type
    """)
    for row in rows:
        print(f"{row['summary_type']}: {row['cnt']}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())

