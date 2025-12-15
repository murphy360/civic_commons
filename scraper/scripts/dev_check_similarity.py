#!/usr/bin/env python3
import asyncio
import asyncpg
import os

async def check():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT similarity($1, $2)",
            'Wellness Seminar: Move Your Body - Twinsburg, OH',
            'Wellness Seminar: Move Your Body'
        )
        print(f'Similarity score: {result}')
    await pool.close()

asyncio.run(check())
