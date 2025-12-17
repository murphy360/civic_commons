"""
Quick test of legislation linking MCP tool.
"""
import asyncio
import json
import asyncpg
import os
from datetime import datetime

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://commons:password@localhost:5432/civic_commons"
)

async def test_legislation_linking():
    """Test creating and retrieving legislation mentions."""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    
    try:
        async with pool.acquire() as conn:
            # Create a test document
            doc_id = await conn.fetchval("""
                INSERT INTO documents (
                    source_id, title, document_type, local_path, published_date, meeting_date
                ) 
                SELECT id, 'Test Agenda', 'agenda', '/tmp/test.pdf', NOW(), NOW()
                FROM sources LIMIT 1
                RETURNING id
            """)
            
            if not doc_id:
                print("ERROR: Could not create test document")
                return
            
            print(f"✓ Created test document {doc_id}")
            
            # Create a legislation mention
            mention_id = await conn.fetchval("""
                INSERT INTO legislation_mentions (
                    document_id,
                    legislation_type,
                    legislation_number,
                    legislation_title,
                    action_taken,
                    vote_result,
                    vote_details,
                    excerpt,
                    mentioned_date
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """, doc_id, 'ordinance', '2025-139', 
                'Water Rate Increase', 'approved', 'passed',
                json.dumps({"yes": 5, "no": 0, "abstain": 0}),
                'The 3% water rate increase was unanimously approved.',
                datetime.now())
            
            print(f"✓ Created legislation mention {mention_id}")
            
            # Query it back
            mentions = await conn.fetch("""
                SELECT 
                    lm.id,
                    lm.legislation_number,
                    lm.legislation_title,
                    lm.action_taken,
                    lm.vote_result,
                    lm.vote_details
                FROM legislation_mentions lm
                WHERE lm.legislation_number = $1
            """, '2025-139')
            
            print(f"✓ Retrieved {len(mentions)} mentions for Ord. 2025-139")
            
            for m in mentions:
                print(f"  - {m['legislation_title']} ({m['action_taken']}): {m['vote_result']}")
            
            # Clean up
            await conn.execute("DELETE FROM legislation_mentions WHERE id = $1", mention_id)
            await conn.execute("DELETE FROM documents WHERE id = $1", doc_id)
            
            print("✓ Cleanup complete")
            print("\nTest PASSED ✓")
            
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(test_legislation_linking())
