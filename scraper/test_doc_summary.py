#!/usr/bin/env python
"""Test document summarization with updated prompts."""

import asyncio
import asyncpg
import os
import sys

from dotenv import load_dotenv
load_dotenv()

# Direct imports bypassing __init__.py
import importlib.util
spec = importlib.util.spec_from_file_location("client", "pipeline/ai/client.py")
client_mod = importlib.util.module_from_spec(spec)
sys.modules["pipeline.ai.client"] = client_mod
spec.loader.exec_module(client_mod)
GeminiClient = client_mod.GeminiClient

spec = importlib.util.spec_from_file_location("doc_summarizer", "pipeline/ai/doc_summarizer.py")
doc_mod = importlib.util.module_from_spec(spec)
sys.modules["pipeline.ai.doc_summarizer"] = doc_mod
spec.loader.exec_module(doc_mod)
DocumentSummarizer = doc_mod.DocumentSummarizer

async def main():
    # Get a document with content
    pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"))
    
    async with pool.acquire() as conn:
        # Get a meeting document (agenda or minutes)
        doc = await conn.fetchrow("""
            SELECT id, title, document_type, local_path, ai_summary
            FROM documents
            WHERE local_path IS NOT NULL
              AND (title ILIKE '%agenda%' OR title ILIKE '%minutes%')
            ORDER BY source_updated_at DESC
            LIMIT 1
        """)
        
        if not doc:
            print("No documents found with local paths")
            return
        
        print(f"Document: {doc['title']}")
        print(f"Type: {doc['document_type']}")
        print(f"Path: {doc['local_path']}")
        print(f"\n--- OLD SUMMARY ---")
        print(doc['ai_summary'] or "(no existing summary)")
        
        # Generate new summary
        client = GeminiClient()
        summarizer = DocumentSummarizer(client)
        
        new_summary = await summarizer.generate_summary(
            title=doc['title'],
            document_type=doc['document_type'],
            local_path=doc['local_path'],
        )
        
        print(f"\n--- NEW SUMMARY ---")
        print(new_summary or "(failed to generate)")
        
        # Update in DB if good
        if new_summary and input("\nUpdate database? (y/n): ").lower() == 'y':
            await conn.execute(
                "UPDATE documents SET ai_summary = $1 WHERE id = $2",
                new_summary, doc['id']
            )
            print("Updated!")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
