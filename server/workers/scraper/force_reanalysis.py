"""
Force re-analysis of recent meeting documents for legislation extraction.
"""
import asyncio
import asyncpg
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://commons:password@localhost:5432/civic_commons"
)

async def force_reanalysis(days_back=30):
    """Clear AI summaries for recent meeting documents to trigger re-analysis."""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    
    try:
        async with pool.acquire() as conn:
            # Find recent meeting docs with summaries
            docs = await conn.fetch("""
                SELECT id, title, document_type, meeting_date
                FROM documents
                WHERE document_type IN ('agenda', 'minutes', 'packet')
                  AND ai_summary IS NOT NULL 
                  AND ai_summary != ''
                  AND (meeting_date >= NOW() - INTERVAL '1 day' * $1 OR meeting_date IS NULL)
                ORDER BY meeting_date DESC NULLS LAST
                LIMIT 20
            """, days_back)
            
            if not docs:
                print(f"No recent meeting documents with summaries found (within {days_back} days)")
                return
            
            print(f"Found {len(docs)} recent documents:")
            for doc in docs:
                meeting_date = doc['meeting_date'].strftime("%Y-%m-%d") if doc['meeting_date'] else "N/A"
                print(f"  - [{doc['id']}] {doc['title'][:60]} ({meeting_date})")
            
            # Clear summaries
            count = await conn.execute("""
                UPDATE documents
                SET ai_summary = NULL
                WHERE id = ANY($1::int[])
            """, [doc['id'] for doc in docs])
            
            print(f"\n✓ Cleared AI summaries for {len(docs)} documents")
            print("They will be re-analyzed on the next AI queue run.")
            print("Check back in a minute or two for legislation extraction results.")
            
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(force_reanalysis())

