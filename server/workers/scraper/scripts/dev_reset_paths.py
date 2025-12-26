#!/usr/bin/env python3
"""Reset incorrectly set document paths."""

import asyncio
import asyncpg
import os


async def reset():
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    async with pool.acquire() as conn:
        # Reset paths that were set incorrectly (absolute /app/data paths)
        result = await conn.execute(
            "UPDATE documents SET local_path = NULL WHERE local_path LIKE '/app/%'"
        )
        print(f'Reset: {result}')
        
        # Check remaining
        docs = await conn.fetch('SELECT id, local_path FROM documents WHERE local_path IS NOT NULL')
        print(f'Documents with local_path: {len(docs)}')
        for doc in docs:
            print(f'  {doc[0]}: {doc[1]}')
    await pool.close()


if __name__ == '__main__':
    asyncio.run(reset())

