#!/usr/bin/env python3
"""Test script to create an annual summary."""
import asyncio
import asyncpg
import os
from datetime import datetime

async def main():
    conn = await asyncpg.connect(dsn=os.environ['DATABASE_URL'])
    
    # Check if one already exists
    existing = await conn.fetchrow("""
        SELECT id FROM summaries
        WHERE city_id = $1 AND summary_type = $2 AND period_start = $3
        AND event_id IS NULL
    """, 'galveston-tx', 'annual', datetime(2024, 1, 1))
    
    if existing:
        print(f"Annual summary already exists with id={existing['id']}")
    else:
        # Create an annual summary for 2024
        result = await conn.fetchval("""
            INSERT INTO summaries (
                city_id, summary_type, period_start, period_end,
                status, is_stale, generation_triggered_by
            ) VALUES (
                $1, $2, $3, $4,
                'pending', true, 'manual-test'
            )
            RETURNING id
        """, 'galveston-tx', 'annual', 
            datetime(2024, 1, 1, 0, 0, 0),
            datetime(2024, 12, 31, 23, 59, 59))
        print(f"Annual summary for 2024 created with id={result}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
