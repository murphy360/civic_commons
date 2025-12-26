"""
Test script for meeting metadata extraction.

This script tests the extract_meeting_metadata function on a specific document
to verify it can extract date, time, and location from agenda/minutes PDFs.
"""
import asyncio
import logging
import os
import sys

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    from pipeline.ai.client import GeminiClient
    from pipeline.ai.doc_summarizer import DocumentSummarizer
    from pipeline.storage import DatabasePool
    
    # Initialize AI client
    client = GeminiClient()
    if not client.enabled:
        logger.error("AI client not enabled - check GEMINI_API_KEY")
        return
    
    summarizer = DocumentSummarizer(client)
    
    # Connect to database
    db_pool = DatabasePool()
    await db_pool.connect()
    
    try:
        async with db_pool.pool.acquire() as conn:
            # Find an agenda document with local_path that has midnight time event
            doc = await conn.fetchrow("""
                SELECT d.id, d.title, d.document_type, d.local_path, d.content_markdown,
                       e.id as event_id, e.start_time, e.location
                FROM documents d
                JOIN event_documents ed ON d.id = ed.document_id
                JOIN events e ON ed.event_id = e.id
                WHERE d.document_type = 'agenda'
                  AND d.local_path IS NOT NULL
                  AND e.start_time::time = '00:00:00'
                ORDER BY e.start_time DESC
                LIMIT 1
            """)
            
            if not doc:
                logger.error("No suitable agenda document found")
                return
            
            logger.info(f"Testing metadata extraction on: {doc['title']}")
            logger.info(f"Document ID: {doc['id']}, Event ID: {doc['event_id']}")
            logger.info(f"Current event time: {doc['start_time']}")
            logger.info(f"Current event location: {doc['location']}")
            logger.info(f"Local path: {doc['local_path']}")
            
            # Test metadata extraction
            metadata = await summarizer.extract_meeting_metadata(
                title=doc['title'],
                document_type=doc['document_type'],
                content_text=doc['content_markdown'],
                local_path=doc['local_path'],
            )
            
            if metadata:
                logger.info("=" * 50)
                logger.info("EXTRACTED METADATA:")
                logger.info(f"  Meeting Date: {metadata.get('meeting_date')}")
                logger.info(f"  Meeting Time: {metadata.get('meeting_time')}")
                logger.info(f"  Location: {metadata.get('location')}")
                logger.info(f"  Meeting Type: {metadata.get('meeting_type')}")
                logger.info(f"  Confidence: {metadata.get('confidence')}")
                logger.info("=" * 50)
                
                # Test update logic
                logger.info("Testing update logic...")
                updated = await db_pool.update_event_from_document_metadata(
                    conn, doc['event_id'], metadata
                )
                if updated:
                    logger.info("Event would be updated with extracted metadata")
                else:
                    logger.info("No updates needed (event may already have values)")
            else:
                logger.warning("No metadata extracted")
                
    finally:
        await db_pool.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
