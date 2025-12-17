"""
Script to clear legislation mentions from documents to trigger re-analysis.

Usage:
    python reprocess_legislation.py [document_ids...]
    
    Or interactively select documents:
    python reprocess_legislation.py --interactive
"""
import asyncio
import sys
import asyncpg
import os
from datetime import datetime

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://commons:password@localhost:5432/civic_commons"
)

async def list_documents_with_mentions():
    """List all documents that have legislation mentions."""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    
    try:
        async with pool.acquire() as conn:
            docs = await conn.fetch("""
                SELECT DISTINCT
                    d.id,
                    d.title,
                    d.document_type,
                    d.published_date,
                    d.meeting_date,
                    COUNT(lm.id) as mention_count
                FROM documents d
                LEFT JOIN legislation_mentions lm ON d.id = lm.document_id
                WHERE lm.id IS NOT NULL
                GROUP BY d.id, d.title, d.document_type, d.published_date, d.meeting_date
                ORDER BY d.published_date DESC
                LIMIT 50
            """)
            
            return docs
    finally:
        await pool.close()

async def clear_legislation_mentions(document_ids):
    """Clear legislation mentions from specified documents."""
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    
    try:
        async with pool.acquire() as conn:
            for doc_id in document_ids:
                # Get document info first
                doc = await conn.fetchrow(
                    "SELECT title FROM documents WHERE id = $1",
                    doc_id
                )
                
                if not doc:
                    print(f"✗ Document {doc_id} not found")
                    continue
                
                # Count current mentions
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM legislation_mentions WHERE document_id = $1",
                    doc_id
                )
                
                if count == 0:
                    print(f"- Document {doc_id} ({doc['title']}) has no mentions")
                    continue
                
                # Delete them
                await conn.execute(
                    "DELETE FROM legislation_mentions WHERE document_id = $1",
                    doc_id
                )
                
                print(f"✓ Cleared {count} mention(s) from document {doc_id}")
                print(f"  Document: {doc['title']}")
                
    finally:
        await pool.close()

async def interactive_mode():
    """Interactive mode to select documents to reprocess."""
    docs = await list_documents_with_mentions()
    
    if not docs:
        print("No documents with legislation mentions found.")
        return
    
    print("\nDocuments with Legislation Mentions:")
    print("=" * 100)
    
    for i, doc in enumerate(docs, 1):
        meeting_date = doc['meeting_date'].strftime("%Y-%m-%d") if doc['meeting_date'] else "N/A"
        pub_date = doc['published_date'].strftime("%Y-%m-%d") if doc['published_date'] else "N/A"
        print(f"{i:2d}. [{doc['id']:4d}] {doc['title'][:60]:<60} ({doc['mention_count']} mentions)")
        print(f"     Type: {doc['document_type']}, Published: {pub_date}, Meeting: {meeting_date}")
    
    print("\n" + "=" * 100)
    
    while True:
        selection = input("\nEnter document numbers to clear (e.g., '1 3 5' or 'all' or 'quit'): ").strip().lower()
        
        if selection == 'quit':
            print("Cancelled.")
            return
        
        if selection == 'all':
            doc_ids = [doc['id'] for doc in docs]
            confirm = input(f"Clear {len(doc_ids)} documents? (yes/no): ").strip().lower()
            if confirm != 'yes':
                continue
        else:
            try:
                indices = [int(x) - 1 for x in selection.split()]
                if any(i < 0 or i >= len(docs) for i in indices):
                    print("Invalid selection. Please try again.")
                    continue
                doc_ids = [docs[i]['id'] for i in indices]
            except (ValueError, IndexError):
                print("Invalid input. Please try again.")
                continue
        
        break
    
    print(f"\nClearing {len(doc_ids)} document(s)...")
    await clear_legislation_mentions(doc_ids)
    print("\nDone! Documents will be re-analyzed on the next AI queue run.")

async def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == '--interactive':
            await interactive_mode()
        else:
            # Direct document IDs provided
            doc_ids = [int(x) for x in sys.argv[1:]]
            print(f"Clearing legislation mentions from {len(doc_ids)} document(s)...")
            await clear_legislation_mentions(doc_ids)
            print("\nDone! Documents will be re-analyzed on the next AI queue run.")
    else:
        # Show help and list available docs
        docs = await list_documents_with_mentions()
        
        if docs:
            print("Recent documents with legislation mentions:")
            print()
            for doc in docs[:10]:
                print(f"  {doc['id']:4d}: {doc['title'][:70]} ({doc['mention_count']} mentions)")
            print(f"\nUsage:")
            print(f"  python reprocess_legislation.py --interactive")
            print(f"  python reprocess_legislation.py 123 456 789")
        else:
            print("No documents with legislation mentions found.")

if __name__ == "__main__":
    asyncio.run(main())
