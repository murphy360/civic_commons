#!/usr/bin/env python3
"""Delete invalid galveston summary."""
import asyncio
import asyncpg
import os

async def main():
    conn = await asyncpg.connect(dsn=os.environ['DATABASE_URL'])
    result = await conn.execute("DELETE FROM summaries WHERE city_id = 'galveston-tx'")
    print(f'Deleted galveston summaries: {result}')
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
