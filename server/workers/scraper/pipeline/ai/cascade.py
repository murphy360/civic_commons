"""
Summary cascade manager.

Handles the database operations and cascade triggering for the summary system.
When a document is added or a summary is updated, this manager ensures all
parent summaries are marked for regeneration.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

import asyncpg

from .summary import (
    SummaryType, 
    SummaryGenerator,
    GeneratedSummary,
    SUMMARY_HIERARCHY,
    get_period_bounds,
    get_parent_period_bounds,
    generate_summary_title,
)

logger = logging.getLogger("civic.ai.cascade")


# Debounce settings - wait before regenerating to batch rapid updates
DEBOUNCE_SECONDS = 60  # Wait 1 minute after last change before regenerating


@dataclass
class CascadeResult:
    """Result of a cascade operation."""
    summaries_marked_stale: int = 0
    summaries_regenerated: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class SummaryCascadeManager:
    """
    Manages summary generation and cascade updates.
    
    Responsibilities:
    - Mark summaries as stale when child content changes
    - Regenerate stale summaries
    - Track trigger history for auditing
    """
    
    def __init__(self, db_pool: asyncpg.Pool, generator: SummaryGenerator):
        """
        Initialize the cascade manager.
        
        Args:
            db_pool: Database connection pool
            generator: SummaryGenerator instance for AI generation
        """
        self._db = db_pool
        self._generator = generator
    
    async def on_document_added(
        self,
        document_id: int,
        event_id: int,
        city_id: str,
    ) -> CascadeResult:
        """
        Handle a new document being added to an event.
        
        Marks the event summary and all parent summaries as stale.
        """
        result = CascadeResult()
        
        try:
            async with self._db.acquire() as conn:
                # Get event details
                event = await conn.fetchrow("""
                    SELECT id, title, start_time FROM events WHERE id = $1
                """, event_id)
                
                if not event:
                    result.errors.append(f"Event {event_id} not found")
                    return result
                
                event_date = event['start_time']
                
                # Mark event summary as stale (or create if doesn't exist)
                await self._mark_or_create_stale(
                    conn, city_id, SummaryType.EVENT, 
                    event_date, event_date, event_id,
                    triggered_by_document=document_id,
                    trigger_reason='document_added'
                )
                result.summaries_marked_stale += 1
                
                # Cascade up the hierarchy
                cascade_count = await self._cascade_stale_marks(
                    conn, city_id, SummaryType.EVENT, event_date,
                    trigger_reason='child_document_added'
                )
                result.summaries_marked_stale += cascade_count
                
        except Exception as e:
            logger.error(f"Error in on_document_added: {e}")
            result.errors.append(str(e))
        
        return result
    
    async def on_event_summary_updated(
        self,
        summary_id: int,
        city_id: str,
        event_date: datetime,
    ) -> CascadeResult:
        """
        Handle an event summary being regenerated.
        
        Marks all parent summaries as stale.
        """
        result = CascadeResult()
        
        try:
            async with self._db.acquire() as conn:
                cascade_count = await self._cascade_stale_marks(
                    conn, city_id, SummaryType.EVENT, event_date,
                    trigger_reason='child_summary_updated',
                    triggered_by_summary=summary_id
                )
                result.summaries_marked_stale += cascade_count
                
        except Exception as e:
            logger.error(f"Error in on_event_summary_updated: {e}")
            result.errors.append(str(e))
        
        return result
    
    async def regenerate_stale_summaries(
        self,
        city_id: Optional[str] = None,
        max_count: int = 10,
    ) -> CascadeResult:
        """
        Regenerate summaries that have been marked as stale.
        
        Processes from most specific (events) to most general (annual)
        to ensure child summaries exist before generating parents.
        """
        result = CascadeResult()
        
        # Process in hierarchy order: EVENT first, then DAILY, etc.
        type_order = [
            SummaryType.EVENT,
            SummaryType.DAILY,
            SummaryType.WEEKLY,
            SummaryType.MONTHLY,
            SummaryType.QUARTERLY,
            SummaryType.ANNUAL,
        ]
        
        remaining = max_count
        
        for summary_type in type_order:
            if remaining <= 0:
                break
            
            count = await self._regenerate_stale_by_type(
                city_id, summary_type, max_count=remaining, result=result
            )
            remaining -= count
        
        return result
    
    async def _regenerate_stale_by_type(
        self,
        city_id: Optional[str],
        summary_type: SummaryType,
        max_count: int,
        result: CascadeResult,
    ) -> int:
        """Regenerate stale summaries of a specific type."""
        regenerated = 0
        
        try:
            async with self._db.acquire() as conn:
                # Find stale or pending summaries that are ready for regeneration
                # (debounce: only if not updated in last DEBOUNCE_SECONDS)
                debounce_cutoff = datetime.now() - timedelta(seconds=DEBOUNCE_SECONDS)
                query = """
                    SELECT s.id, s.city_id, s.event_id, s.period_start, s.period_end,
                           c.display_name as city_name
                    FROM summaries s
                    JOIN cities c ON s.city_id = c.city_id
                    WHERE (s.is_stale = true OR s.status = 'pending')
                      AND s.summary_type = $1
                      AND s.updated_at < $2
                """
                params = [summary_type.value, debounce_cutoff]
                
                if city_id:
                    query += " AND s.city_id = $3"
                    params.append(city_id)
                
                query += " ORDER BY s.period_start DESC LIMIT $" + str(len(params) + 1)
                params.append(max_count)
                
                stale = await conn.fetch(query, *params)
                
                for row in stale:
                    try:
                        success = await self._regenerate_summary(
                            conn, row, summary_type
                        )
                        if success:
                            regenerated += 1
                            result.summaries_regenerated += 1
                    except Exception as e:
                        error_msg = f"Error regenerating {summary_type.value} summary {row['id']}: {e}"
                        logger.error(error_msg)
                        result.errors.append(error_msg)
        
        except Exception as e:
            logger.error(f"Error in _regenerate_stale_by_type: {e}")
            result.errors.append(str(e))
        
        return regenerated
    
    async def _regenerate_summary(
        self,
        conn: asyncpg.Connection,
        summary_row: asyncpg.Record,
        summary_type: SummaryType,
    ) -> bool:
        """Regenerate a single summary."""
        summary_id = summary_row['id']
        city_id = summary_row['city_id']
        city_name = summary_row['city_name']
        period_start = summary_row['period_start']
        period_end = summary_row['period_end']
        event_id = summary_row['event_id']
        
        # Mark as generating
        await conn.execute("""
            UPDATE summaries 
            SET status = 'generating', generation_started_at = NOW()
            WHERE id = $1
        """, summary_id)
        
        try:
            if summary_type == SummaryType.EVENT:
                result = await self._generate_event_summary(
                    conn, event_id, city_name
                )
            else:
                result = await self._generate_period_summary(
                    conn, city_id, city_name, summary_type, period_start, period_end
                )
            
            if result:
                # Update the summary with model info
                title = generate_summary_title(summary_type, period_end, city_name)
                await conn.execute("""
                    UPDATE summaries 
                    SET summary_text = $2, title = $3, 
                        status = 'completed', is_stale = false,
                        generation_completed_at = NOW(),
                        model_used = $4,
                        version = version + 1
                    WHERE id = $1
                """, summary_id, result.text_with_footer, title, result.model_name)
                
                # For event summaries, also update the events table ai_summary
                if summary_type == SummaryType.EVENT and event_id:
                    await conn.execute("""
                        UPDATE events 
                        SET ai_summary = $1, ai_summary_updated_at = NOW(), ai_model_used = $2
                        WHERE id = $3
                    """, result.text_with_footer, result.model_name, event_id)
                    logger.info(f"Also updated events.ai_summary for event {event_id}")
                
                logger.info(f"Regenerated {summary_type.value} summary {summary_id} using {result.model_name}")
                return True
            else:
                # Mark as failed
                await conn.execute("""
                    UPDATE summaries 
                    SET status = 'failed', is_stale = false,
                        error_message = 'No content generated'
                    WHERE id = $1
                """, summary_id)
                return False
                
        except Exception as e:
            # Mark as failed
            await conn.execute("""
                UPDATE summaries 
                SET status = 'failed', is_stale = false,
                    error_message = $2
                WHERE id = $1
            """, summary_id, str(e))
            raise
    
    async def _generate_event_summary(
        self,
        conn: asyncpg.Connection,
        event_id: int,
        city_name: str,
    ) -> Optional[GeneratedSummary]:
        """Generate summary for an event from its documents."""
        # Get event details
        event = await conn.fetchrow("""
            SELECT id, title, start_time, ai_summary 
            FROM events WHERE id = $1
        """, event_id)
        
        if not event:
            return None
        
        # Get all documents for the event
        documents = await conn.fetch("""
            SELECT d.id, d.title, d.document_type, d.ai_summary, 
                   LEFT(d.content_text, 3000) as content_text
            FROM documents d
            JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.event_id = $1
            ORDER BY d.created_at
        """, event_id)
        
        if not documents:
            return None
        
        docs_list = [
            {
                'title': d['title'],
                'doc_type': d['document_type'],
                'ai_summary': d['ai_summary'],
                'content': d['content_text'],
            }
            for d in documents
        ]
        
        return await self._generator.generate_event_summary(
            event_title=event['title'],
            event_date=event['start_time'],
            documents=docs_list,
            city_name=city_name,
            existing_summary=event['ai_summary'],
        )
    
    async def _generate_period_summary(
        self,
        conn: asyncpg.Connection,
        city_id: str,
        city_name: str,
        summary_type: SummaryType,
        period_start: datetime,
        period_end: datetime,
    ) -> Optional[GeneratedSummary]:
        """Generate a period summary from child summaries."""
        # Determine child type
        child_type = None
        for ct, pt in SUMMARY_HIERARCHY.items():
            if pt == summary_type:
                child_type = ct
                break
        
        # Get child summaries
        if child_type == SummaryType.EVENT:
            # For daily summaries, get event summaries
            child_summaries = await conn.fetch("""
                SELECT s.id, s.title, s.summary_text, s.period_start,
                       e.title as event_title
                FROM summaries s
                JOIN events e ON s.event_id = e.id
                WHERE s.city_id = $1
                  AND s.summary_type = 'event'
                  AND s.period_start >= $2 AND s.period_start < $3
                  AND s.status = 'completed'
                ORDER BY s.period_start
            """, city_id, period_start, period_end)
        else:
            # For higher-level summaries, get period summaries
            child_summaries = await conn.fetch("""
                SELECT id, title, summary_text, period_start
                FROM summaries
                WHERE city_id = $1
                  AND summary_type = $2
                  AND period_start >= $3 AND period_start < $4
                  AND status = 'completed'
                ORDER BY period_start
            """, city_id, child_type.value, period_start, period_end)
        
        # Also get events directly (fallback if no child summaries)
        events = await conn.fetch("""
            SELECT id, title, start_time, ai_summary, description
            FROM events
            WHERE start_time >= $1 AND start_time < $2
            ORDER BY start_time
        """, period_start, period_end)
        
        child_list = [
            {
                'title': c['title'],
                'summary_text': c['summary_text'],
                'period_start': c['period_start'],
            }
            for c in child_summaries
        ]
        
        events_list = [
            {
                'title': e['title'],
                'start_time': e['start_time'],
                'ai_summary': e['ai_summary'],
                'description': e['description'],
            }
            for e in events
        ]
        
        return await self._generator.generate_period_summary(
            summary_type=summary_type,
            period_start=period_start,
            period_end=period_end,
            city_name=city_name,
            child_summaries=child_list,
            events=events_list,
        )
    
    async def _mark_or_create_stale(
        self,
        conn: asyncpg.Connection,
        city_id: str,
        summary_type: SummaryType,
        period_start: datetime,
        period_end: datetime,
        event_id: Optional[int] = None,
        triggered_by_document: Optional[int] = None,
        triggered_by_summary: Optional[int] = None,
        trigger_reason: str = 'unknown',
    ) -> int:
        """Mark an existing summary as stale or create a new pending one."""
        
        if event_id:
            # Event summary - unique by event
            existing = await conn.fetchrow("""
                SELECT id FROM summaries
                WHERE city_id = $1 AND event_id = $2
            """, city_id, event_id)
        else:
            # Period summary - unique by type and period
            existing = await conn.fetchrow("""
                SELECT id FROM summaries
                WHERE city_id = $1 AND summary_type = $2 AND period_start = $3
                  AND event_id IS NULL
            """, city_id, summary_type.value, period_start)
        
        if existing:
            # Mark as stale
            await conn.execute("""
                UPDATE summaries 
                SET is_stale = true, 
                    generation_triggered_by = $2,
                    triggered_by_id = $3
                WHERE id = $1
            """, existing['id'], trigger_reason, 
               triggered_by_document or triggered_by_summary)
            summary_id = existing['id']
        else:
            # Create new pending summary
            summary_id = await conn.fetchval("""
                INSERT INTO summaries (
                    city_id, summary_type, period_start, period_end, event_id,
                    status, is_stale, generation_triggered_by, triggered_by_id
                ) VALUES ($1, $2, $3, $4, $5, 'pending', true, $6, $7)
                RETURNING id
            """, city_id, summary_type.value, period_start, period_end, event_id,
               trigger_reason, triggered_by_document or triggered_by_summary)
        
        # Log the trigger
        await conn.execute("""
            INSERT INTO summary_triggers (
                summary_id, triggered_by_document_id, triggered_by_summary_id, trigger_reason
            ) VALUES ($1, $2, $3, $4)
        """, summary_id, triggered_by_document, triggered_by_summary, trigger_reason)
        
        return summary_id
    
    async def _cascade_stale_marks(
        self,
        conn: asyncpg.Connection,
        city_id: str,
        child_type: SummaryType,
        child_date: datetime,
        trigger_reason: str = 'child_updated',
        triggered_by_summary: Optional[int] = None,
    ) -> int:
        """Mark all parent summaries as stale, cascading up the hierarchy."""
        marked_count = 0
        current_type = child_type
        current_date = child_date
        
        while True:
            parent_info = get_parent_period_bounds(current_type, current_date)
            if parent_info is None:
                break
            
            parent_type, parent_start, parent_end = parent_info
            
            await self._mark_or_create_stale(
                conn, city_id, parent_type, parent_start, parent_end,
                event_id=None,
                triggered_by_summary=triggered_by_summary,
                trigger_reason=trigger_reason,
            )
            marked_count += 1
            
            current_type = parent_type
            current_date = parent_start
        
        return marked_count
    
    async def ensure_period_summaries_exist(
        self,
        city_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> int:
        """
        Ensure all period summaries exist for a date range.
        
        Creates pending/stale summaries for any missing periods.
        Useful when backfilling data.
        """
        created = 0
        
        async with self._db.acquire() as conn:
            # For each summary type (daily, weekly, etc.)
            for summary_type in [SummaryType.DAILY, SummaryType.WEEKLY, 
                                SummaryType.MONTHLY, SummaryType.QUARTERLY,
                                SummaryType.ANNUAL]:
                
                # Calculate all periods in the range
                current = start_date
                while current <= end_date:
                    period_start, period_end = get_period_bounds(summary_type, current)
                    
                    # Check if exists
                    existing = await conn.fetchrow("""
                        SELECT id FROM summaries
                        WHERE city_id = $1 AND summary_type = $2 AND period_start = $3
                          AND event_id IS NULL
                    """, city_id, summary_type.value, period_start)
                    
                    if not existing:
                        await conn.execute("""
                            INSERT INTO summaries (
                                city_id, summary_type, period_start, period_end,
                                status, is_stale, generation_triggered_by
                            ) VALUES ($1, $2, $3, $4, 'pending', true, 'backfill')
                        """, city_id, summary_type.value, period_start, period_end)
                        created += 1
                    
                    # Move to next period
                    if summary_type == SummaryType.DAILY:
                        current += timedelta(days=1)
                    elif summary_type == SummaryType.WEEKLY:
                        current += timedelta(weeks=1)
                    elif summary_type == SummaryType.MONTHLY:
                        if current.month == 12:
                            current = current.replace(year=current.year + 1, month=1)
                        else:
                            current = current.replace(month=current.month + 1)
                    elif summary_type == SummaryType.QUARTERLY:
                        if current.month >= 10:
                            current = current.replace(year=current.year + 1, month=1)
                        else:
                            current = current.replace(month=current.month + 3)
                    elif summary_type == SummaryType.ANNUAL:
                        current = current.replace(year=current.year + 1)
        
        logger.info(f"Created {created} pending period summaries for {city_id}")
        return created

