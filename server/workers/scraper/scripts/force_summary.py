#!/usr/bin/env python3
"""
Force generation of summaries (bypasses debounce).

Usage:
    python force_summary.py [--type TYPE] [--city CITY_ID]
    
Examples:
    python force_summary.py                    # Generate all stale summaries
    python force_summary.py --type daily       # Generate only daily summaries
    python force_summary.py --type event --city twinsburg  # Generate event summaries for Twinsburg
"""

import asyncio
import argparse
import logging
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg

from pipeline.ai.summary import SummaryType, SummaryGenerator, GeneratedSummary, generate_summary_title
from pipeline.ai.client import GeminiClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("force_summary")


async def force_regenerate_summary(
    conn: asyncpg.Connection,
    generator: SummaryGenerator,
    summary_id: int,
    summary_type: SummaryType,
    city_id: str,
    city_name: str,
    period_start,
    period_end,
    event_id: int = None,
):
    """Force regenerate a single summary."""
    logger.info(f"Regenerating {summary_type.value} summary {summary_id} for {city_name}")
    
    # Mark as generating
    await conn.execute("""
        UPDATE summaries 
        SET status = 'generating', generation_started_at = NOW()
        WHERE id = $1
    """, summary_id)
    
    try:
        if summary_type == SummaryType.EVENT:
            result = await generate_event_summary(conn, generator, event_id, city_name)
        else:
            result = await generate_period_summary(
                conn, generator, city_id, city_name, summary_type, period_start, period_end
            )
        
        if result:
            title = generate_summary_title(summary_type, period_end, city_name)
            await conn.execute("""
                UPDATE summaries 
                SET summary_text = $2, title = $3, 
                    status = 'completed', is_stale = false,
                    generation_completed_at = NOW(),
                    model_used = $4,
                    version = version + 1
                WHERE id = $1
            """, summary_id, result.text, title, result.model_name)
            
            logger.info(f"✓ Completed {summary_type.value} summary {summary_id}: {title} (model: {result.model_name})")
            return True
        else:
            await conn.execute("""
                UPDATE summaries 
                SET status = 'failed', is_stale = false,
                    error_message = 'No content generated'
                WHERE id = $1
            """, summary_id)
            logger.warning(f"✗ No content generated for summary {summary_id}")
            return False
            
    except Exception as e:
        await conn.execute("""
            UPDATE summaries 
            SET status = 'failed', is_stale = false,
                error_message = $2
            WHERE id = $1
        """, summary_id, str(e))
        logger.error(f"✗ Error generating summary {summary_id}: {e}")
        raise


async def generate_event_summary(
    conn: asyncpg.Connection,
    generator: SummaryGenerator,
    event_id: int,
    city_name: str,
):
    """Generate summary for an event from its documents."""
    event = await conn.fetchrow("""
        SELECT id, title, start_time, ai_summary 
        FROM events WHERE id = $1
    """, event_id)
    
    if not event:
        logger.warning(f"Event {event_id} not found")
        return None
    
    documents = await conn.fetch("""
        SELECT d.id, d.title, d.document_type, d.ai_summary, 
               LEFT(d.content_text, 3000) as content_text
        FROM documents d
        JOIN event_documents ed ON d.id = ed.document_id
        WHERE ed.event_id = $1
        ORDER BY d.created_at
    """, event_id)
    
    if not documents:
        logger.warning(f"No documents for event {event_id}")
        return None
    
    logger.info(f"  - Event: {event['title']} ({len(documents)} documents)")
    
    docs_list = [
        {
            'title': d['title'],
            'doc_type': d['document_type'],
            'ai_summary': d['ai_summary'],
            'content': d['content_text'],
        }
        for d in documents
    ]
    
    return await generator.generate_event_summary(
        event_title=event['title'],
        event_date=event['start_time'],
        documents=docs_list,
        city_name=city_name,
        existing_summary=event['ai_summary'],
    )


async def generate_period_summary(
    conn: asyncpg.Connection,
    generator: SummaryGenerator,
    city_id: str,
    city_name: str,
    summary_type: SummaryType,
    period_start,
    period_end,
):
    """Generate a period summary from child summaries."""
    # Determine child type
    child_type_map = {
        SummaryType.DAILY: SummaryType.EVENT,
        SummaryType.WEEKLY: SummaryType.DAILY,
        SummaryType.MONTHLY: SummaryType.WEEKLY,
        SummaryType.QUARTERLY: SummaryType.MONTHLY,
        SummaryType.ANNUAL: SummaryType.QUARTERLY,
    }
    
    child_type = child_type_map.get(summary_type)
    if not child_type:
        return None
    
    # Get child summaries
    if child_type == SummaryType.EVENT:
        # For daily: get event summaries that fall within this day
        children = await conn.fetch("""
            SELECT s.id, s.title, s.summary_text, s.period_start, s.event_id,
                   e.title as event_title
            FROM summaries s
            LEFT JOIN events e ON s.event_id = e.id
            WHERE s.city_id = $1
              AND s.summary_type = 'event'
              AND s.period_start >= $2
              AND s.period_start < $3
              AND s.status = 'completed'
            ORDER BY s.period_start
        """, city_id, period_start, period_end)
    else:
        # For weekly/monthly/etc: get child period summaries
        children = await conn.fetch("""
            SELECT id, title, summary_text, period_start, period_end
            FROM summaries 
            WHERE city_id = $1
              AND summary_type = $2
              AND period_start >= $3
              AND period_start < $4
              AND status = 'completed'
            ORDER BY period_start
        """, city_id, child_type.value, period_start, period_end)
    
    if not children:
        logger.warning(f"No completed child summaries for {summary_type.value} ({period_start} to {period_end})")
        return None
    
    logger.info(f"  - Found {len(children)} child {child_type.value} summaries")
    
    child_summaries = [
        {
            'title': c['title'] or c.get('event_title', 'Untitled'),
            'summary_text': c['summary_text'],
            'period_start': c['period_start'],
        }
        for c in children
    ]
    
    return await generator.generate_period_summary(
        summary_type=summary_type,
        period_start=period_start,
        period_end=period_end,
        child_summaries=child_summaries,
        city_name=city_name,
    )


async def main():
    parser = argparse.ArgumentParser(description='Force summary generation')
    parser.add_argument('--type', '-t', choices=['event', 'daily', 'weekly', 'monthly', 'quarterly', 'annual'],
                       help='Summary type to generate (default: all)')
    parser.add_argument('--city', '-c', help='City ID to filter by')
    parser.add_argument('--limit', '-l', type=int, default=10, help='Max summaries to generate')
    args = parser.parse_args()
    
    # Database connection
    db_url = os.environ.get('DATABASE_URL', 'postgresql://commons:commons@localhost:5432/civic_commons')
    pool = await asyncpg.create_pool(db_url)
    
    # Initialize generator
    gemini_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_AI_API_KEY')
    if not gemini_key:
        logger.error("No GEMINI_API_KEY or GOOGLE_AI_API_KEY found")
        return
    
    gemini_client = GeminiClient(api_key=gemini_key)
    generator = SummaryGenerator(gemini_client)
    
    # Process in hierarchy order
    type_order = [
        SummaryType.EVENT,
        SummaryType.DAILY,
        SummaryType.WEEKLY,
        SummaryType.MONTHLY,
        SummaryType.QUARTERLY,
        SummaryType.ANNUAL,
    ]
    
    if args.type:
        type_order = [SummaryType(args.type)]
    
    total_generated = 0
    
    async with pool.acquire() as conn:
        for summary_type in type_order:
            if total_generated >= args.limit:
                break
            
            # Build query
            query = """
                SELECT s.id, s.city_id, s.event_id, s.period_start, s.period_end,
                       c.display_name as city_name
                FROM summaries s
                JOIN cities c ON s.city_id = c.city_id
                WHERE s.is_stale = true
                  AND s.summary_type = $1
            """
            params = [summary_type.value]
            
            if args.city:
                query += " AND s.city_id = $2"
                params.append(args.city)
            
            query += " ORDER BY s.period_start DESC LIMIT $" + str(len(params) + 1)
            params.append(args.limit - total_generated)
            
            rows = await conn.fetch(query, *params)
            
            if not rows:
                logger.info(f"No stale {summary_type.value} summaries found")
                continue
            
            logger.info(f"\n=== Processing {len(rows)} {summary_type.value} summaries ===")
            
            for row in rows:
                try:
                    success = await force_regenerate_summary(
                        conn, generator,
                        summary_id=row['id'],
                        summary_type=summary_type,
                        city_id=row['city_id'],
                        city_name=row['city_name'],
                        period_start=row['period_start'],
                        period_end=row['period_end'],
                        event_id=row['event_id'],
                    )
                    if success:
                        total_generated += 1
                except Exception as e:
                    logger.error(f"Failed: {e}")
    
    await pool.close()
    logger.info(f"\n=== Complete: {total_generated} summaries generated ===")


if __name__ == '__main__':
    asyncio.run(main())

