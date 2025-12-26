#!/usr/bin/env python3
"""
Backfill script to extract legislation mentions from documents that already have AI summaries.

This is needed because the legislation_mentions table was added after many documents were processed.
Documents with summaries but no legislation mentions will be processed.

Usage:
    # Run in scraper container:
    docker compose exec scraper python extract_legislation_backfill.py

    # Or limit to specific document types:
    docker compose exec scraper python extract_legislation_backfill.py --types ordinance resolution

    # Or limit to specific source:
    docker compose exec scraper python extract_legislation_backfill.py --source "City of Twinsburg"
"""
import asyncio
import sys
import os
import argparse
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from pipeline.ai.doc_summarizer import DocumentSummarizer


async def get_documents_needing_extraction(conn, document_types: list = None, source_name: str = None, limit: int = 100):
    """Get documents with AI summaries but no legislation mentions."""
    
    query = """
        SELECT 
            d.id,
            d.title,
            d.document_type,
            d.content_markdown,
            d.local_path,
            d.meeting_date,
            s.name as source_name
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        WHERE d.ai_summary IS NOT NULL 
          AND d.ai_summary != ''
          AND NOT EXISTS (
              SELECT 1 FROM legislation_mentions lm WHERE lm.document_id = d.id
          )
    """
    
    params = []
    param_idx = 1
    
    if document_types:
        query += f" AND d.document_type = ANY(${param_idx}::text[])"
        params.append(document_types)
        param_idx += 1
    else:
        # Default to legislation-related document types
        query += f" AND d.document_type IN ('ordinance', 'resolution', 'agenda', 'minutes', 'packet')"
    
    if source_name:
        query += f" AND s.name ILIKE ${param_idx}"
        params.append(f"%{source_name}%")
        param_idx += 1
    
    query += f" ORDER BY d.meeting_date DESC NULLS LAST LIMIT ${param_idx}"
    params.append(limit)
    
    return await conn.fetch(query, *params)


async def extract_legislation_for_document(conn, summarizer, doc):
    """Extract legislation mentions from a single document."""
    
    try:
        # Extract legislation mentions from the document
        legislation_list = await summarizer.extract_legislation(
            title=doc["title"],
            document_type=doc["document_type"],
            content_text=doc["content_markdown"],
            local_path=doc["local_path"],
        )
        
        if not legislation_list:
            logger.debug(f"No legislation found in '{doc['title']}'")
            return 0
        
        logger.info(f"Extracted {len(legislation_list)} legislation mentions from '{doc['title']}'")
        
        # Try to find linked event for this document
        event_id = await conn.fetchval("""
            SELECT event_id FROM event_documents WHERE document_id = $1 LIMIT 1
        """, doc["id"])
        
        mentions_created = 0
        
        # Store each legislation mention
        for legis in legislation_list:
            try:
                # Extract fields with defaults
                legis_type = (legis.get("type") or "").lower().strip()
                legis_number = (legis.get("number") or "").strip()
                legis_title = (legis.get("title") or "").strip() or None
                action = (legis.get("action") or "discussed").lower().strip()
                vote_result = (legis.get("vote_result") or "").strip() or None
                vote_details = (legis.get("vote_details") or "").strip() or None
                excerpt = (legis.get("excerpt") or "").strip() or None
                
                if not legis_type or not legis_number:
                    logger.debug(f"Skipping legislation with missing type or number: {legis}")
                    continue
                
                mentioned_date = doc["meeting_date"]
                
                # Check if this mention already exists
                existing = await conn.fetchrow("""
                    SELECT id FROM legislation_mentions
                    WHERE document_id = $1
                      AND legislation_number = $2
                      AND action_taken = $3
                """, doc["id"], legis_number, action)
                
                if existing:
                    # Update existing
                    await conn.execute("""
                        UPDATE legislation_mentions
                        SET legislation_title = COALESCE($2, legislation_title),
                            vote_result = COALESCE($3, vote_result),
                            vote_details = COALESCE($4, vote_details),
                            excerpt = COALESCE($5, excerpt),
                            event_id = COALESCE($6, event_id),
                            updated_at = NOW()
                        WHERE id = $1
                    """, existing["id"], legis_title, vote_result,
                        vote_details, excerpt, event_id)
                    logger.debug(f"Updated legislation mention: {legis_type} {legis_number} ({action})")
                else:
                    # Create new
                    await conn.execute("""
                        INSERT INTO legislation_mentions (
                            document_id,
                            event_id,
                            legislation_type,
                            legislation_number,
                            legislation_title,
                            action_taken,
                            vote_result,
                            vote_details,
                            excerpt,
                            mentioned_date
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """, doc["id"], event_id, legis_type, legis_number,
                        legis_title, action, vote_result, vote_details,
                        excerpt, mentioned_date)
                    logger.debug(f"Created legislation mention: {legis_type} {legis_number} ({action})")
                    mentions_created += 1
                    
            except Exception as e:
                logger.warning(f"Failed to store legislation mention: {e}")
                continue
        
        return mentions_created
        
    except Exception as e:
        logger.warning(f"Legislation extraction failed for '{doc['title']}': {e}")
        return 0


async def main():
    parser = argparse.ArgumentParser(description="Backfill legislation mentions from existing document summaries")
    parser.add_argument("--types", nargs="+", help="Document types to process (e.g., ordinance resolution)")
    parser.add_argument("--source", type=str, help="Filter by source name (e.g., 'City of Twinsburg')")
    parser.add_argument("--limit", type=int, default=100, help="Maximum documents to process (default: 100)")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually extract, just show what would be processed")
    
    args = parser.parse_args()
    
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://commons:password@localhost:5432/civic_commons"
    )
    
    logger.info("Starting legislation mention backfill...")
    logger.info(f"Database: {database_url.split('@')[-1]}")
    
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    
    try:
        async with pool.acquire() as conn:
            # Get documents needing extraction
            docs = await get_documents_needing_extraction(
                conn,
                document_types=args.types,
                source_name=args.source,
                limit=args.limit
            )
            
            if not docs:
                logger.info("No documents found needing legislation extraction")
                return
            
            logger.info(f"Found {len(docs)} documents to process")
            
            if args.dry_run:
                logger.info("DRY RUN - would process these documents:")
                for doc in docs:
                    logger.info(f"  [{doc['id']}] {doc['title'][:80]} ({doc['document_type']})")
                return
            
            # Initialize summarizer for extraction
            summarizer = DocumentSummarizer()
            if not summarizer.enabled:
                logger.error("DocumentSummarizer not enabled (check GEMINI_API_KEY)")
                return
            
            total_mentions = 0
            docs_processed = 0
            
            for doc in docs:
                logger.info(f"Processing [{doc['id']}] {doc['title'][:60]}...")
                
                mentions = await extract_legislation_for_document(conn, summarizer, doc)
                total_mentions += mentions
                docs_processed += 1
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)
            
            logger.info(f"Backfill complete!")
            logger.info(f"  Documents processed: {docs_processed}")
            logger.info(f"  Legislation mentions created: {total_mentions}")
            
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

