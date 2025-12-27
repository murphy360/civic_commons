"""
Cascade Service - Background worker for AI analysis orchestration.

This service is the central orchestrator for all AI processing:
1. Monitors for documents/videos needing AI summaries
2. Processes them in priority order (documents → events → period summaries)
3. Triggers cascade updates when summaries complete

Runs as a separate service, calling MCP server endpoints for AI processing.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import asyncpg
import httpx

logger = logging.getLogger("civic_commons.cascade_service")


class CascadeService:
    """
    Background service that orchestrates AI analysis and summary cascades.
    
    Runs independently, queries database for items needing AI processing,
    and calls MCP server endpoints to generate summaries.
    """
    
    def __init__(self, mcp_url: str = "http://localhost:8000", db_url: Optional[str] = None):
        """
        Initialize cascade service.
        
        Args:
            mcp_url: URL of MCP server (default: localhost:8000)
            db_url: Database URL (optional - can be loaded from env)
        """
        self.mcp_url = mcp_url.rstrip("/")
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self._http_client: Optional[httpx.AsyncClient] = None
        self._db_pool: Optional[asyncpg.Pool] = None
        self._running = False
        
        # Configuration
        self.ai_batch_size = int(os.getenv("AI_BATCH_SIZE", "5"))
        self.ai_interval_seconds = int(os.getenv("AI_INTERVAL_SECONDS", "30"))
        self.max_age_days = int(os.getenv("AI_SUMMARY_MAX_AGE_DAYS", "365"))
    
    async def start(self) -> None:
        """Start the cascade service."""
        # Videos can take 10-15+ minutes to process through Gemini for long council meetings
        self._http_client = httpx.AsyncClient(timeout=900.0)  # 15 min for long videos
        self._db_pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=5)
        self._running = True
        
        logger.info("=" * 60)
        logger.info(f"CASCADE SERVICE STARTED")
        logger.info(f"  MCP Server: {self.mcp_url}")
        logger.info(f"  AI Batch Size: {self.ai_batch_size}")
        logger.info(f"  AI Interval: {self.ai_interval_seconds}s")
        logger.info(f"  Max Age: {self.max_age_days} days")
        logger.info("=" * 60)
        
        # Log startup to activity_log
        await self._log_activity("success", "system", "startup", "CASCADE SERVICE - Service started")
        
        try:
            await self._main_loop()
        except asyncio.CancelledError:
            logger.info("Cascade service cancelled")
        except Exception as e:
            logger.error(f"Cascade service error: {e}")
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the cascade service."""
        self._running = False
        
        await self._log_activity("info", "system", "shutdown", "CASCADE SERVICE - Service stopped")
        
        if self._http_client:
            await self._http_client.aclose()
        if self._db_pool:
            await self._db_pool.close()
        logger.info("Cascade service stopped")
    
    async def _log_activity(
        self, level: str, category: str, action: str, message: str,
        entity_type: str = None, entity_id: int = None, entity_title: str = None,
        details: dict = None
    ) -> None:
        """Log activity to database for admin visibility."""
        if not self._db_pool:
            return
        try:
            import json
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO activity_log 
                    (level, category, action, message, entity_type, entity_id, entity_title, details)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, level, category, action, message, entity_type, entity_id, entity_title,
                     json.dumps(details) if details else None)
        except Exception as e:
            logger.warning(f"Failed to log activity: {e}")
    
    async def _main_loop(self) -> None:
        """
        Main processing loop.
        
        Alternates between:
        1. Processing AI analysis queue (documents, videos, events, summaries)
        2. Checking for cascade triggers (completed summaries that need propagation)
        """
        while self._running:
            try:
                # Process AI analysis queue
                processed = await self._process_ai_queue()
                
                if processed > 0:
                    logger.info(f"AI queue: Processed {processed} items")
                
                # Check for cascade triggers (documents with new summaries)
                cascaded = await self._process_cascade_triggers()
                
                if cascaded > 0:
                    logger.info(f"Cascade: Triggered {cascaded} updates")
                
                # Wait before next iteration
                await asyncio.sleep(self.ai_interval_seconds)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(60)  # Longer wait on error
    
    async def _process_ai_queue(self) -> int:
        """
        Process items from the AI analysis queue.
        
        Priority order (by tier, within each date newest-first):
        1. Documents (extracted text ready for summary)
        2. Videos (YouTube URLs ready for transcript + summary)
        3. Events (all linked documents summarized)
        4. Daily summaries (all events for that day summarized)
        5. Weekly summaries (all daily summaries in that week complete)
        6. Monthly summaries (all weekly summaries in that month complete)
        7. Quarterly summaries (all monthly summaries in that quarter complete)
        8. Annual summaries (all quarterly summaries in that year complete)
        
        When a new document arrives for an old date, cascade invalidation marks
        all dependent summaries as stale, causing them to be re-queued here.
        
        Returns number of items processed.
        """
        processed = 0
        
        async with self._db_pool.acquire() as conn:
            # Get items from unified AI queue
            items = await self._get_ai_queue(conn)
            
            if not items:
                logger.debug("AI queue: No items pending")
                return 0
            
            # Log what we're processing
            item_types = {}
            for item in items:
                t = item['item_type']
                item_types[t] = item_types.get(t, 0) + 1
            logger.info(f"AI queue: Processing {len(items)} items ({item_types})")
            
            for item in items:
                try:
                    item_type = item['item_type']
                    item_id = item['id']
                    title = item['title']
                    
                    logger.debug(f"Processing {item_type} {item_id}: {title[:50]}...")
                    
                    success = False
                    if item_type == 'document':
                        success = await self._process_document(conn, item)
                    elif item_type == 'video':
                        success = await self._process_video(conn, item)
                    elif item_type == 'event':
                        success = await self._process_event(conn, item)
                    elif item_type == 'summary':
                        success = await self._process_summary(conn, item)
                    
                    if success:
                        processed += 1
                        
                except Exception as e:
                    logger.warning(f"Failed to process {item['item_type']} {item['id']}: {e}")
                    # Mark as failed with retry increment
                    await self._mark_failed(conn, item, str(e))
        
        return processed
    
    async def _get_ai_queue(self, conn) -> list:
        """
        Get unified AI queue with proper dependency ordering.
        
        Uses the same query logic as the scraper's queue_manager.
        """
        effective_max_age = self.max_age_days if self.max_age_days > 0 else 36500
        
        return await conn.fetch("""
            SELECT * FROM (
                -- TIER 1: Documents ready for AI (highest priority)
                SELECT 
                    id,
                    'document'::text as item_type,
                    title,
                    document_type,
                    NULL::varchar as summary_type,
                    COALESCE(meeting_date, created_at) as item_date,
                    content_markdown,
                    local_path,
                    source_url,
                    source_id,
                    1 as priority_tier,
                    COALESCE(retry_count, 0) as retry_count,
                    summary_priority
                FROM documents
                WHERE content_status IN ('extracted', 'ai_pending')
                  AND content_markdown IS NOT NULL
                  AND document_type != 'video'
                  AND COALESCE(retry_count, 0) < 3
                  AND COALESCE(meeting_date, created_at) >= NOW() - INTERVAL '1 day' * $1
                
                UNION ALL
                
                -- TIER 1: Videos ready for AI (same priority as documents)
                SELECT 
                    id,
                    'video'::text as item_type,
                    title,
                    'video' as document_type,
                    NULL::varchar as summary_type,
                    COALESCE(meeting_date, created_at) as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    source_url,
                    source_id,
                    1 as priority_tier,
                    COALESCE(retry_count, 0) as retry_count,
                    summary_priority
                FROM documents
                WHERE content_status = 'ai_pending'
                  AND document_type = 'video'
                  AND source_url LIKE '%youtu%'
                  AND COALESCE(retry_count, 0) < 3
                  AND COALESCE(meeting_date, created_at) >= NOW() - INTERVAL '1 day' * $1
                
                UNION ALL
                
                -- TIER 2: Events where ALL linked documents have AI summaries
                SELECT 
                    e.id,
                    'event'::text as item_type,
                    e.title,
                    NULL as document_type,
                    NULL::varchar as summary_type,
                    COALESCE(e.start_time, e.created_at) as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    NULL::integer as source_id,
                    2 as priority_tier,
                    0 as retry_count,
                    e.summary_priority
                FROM events e
                WHERE (e.ai_summary IS NULL OR e.ai_summary = '')
                  AND COALESCE(e.start_time, e.created_at) >= NOW() - INTERVAL '1 day' * $1
                  AND NOT EXISTS (
                      SELECT 1 FROM event_documents ed
                      JOIN documents d ON ed.document_id = d.id
                      WHERE ed.event_id = e.id
                        AND (d.ai_summary IS NULL OR d.ai_summary = '')
                        AND d.content_status NOT IN ('skipped', 'failed')
                  )
                  AND EXISTS (
                      SELECT 1 FROM event_documents ed
                      JOIN documents d ON ed.document_id = d.id
                      WHERE ed.event_id = e.id
                        AND d.ai_summary IS NOT NULL
                        AND d.ai_summary != ''
                  )
                
                UNION ALL
                
                -- TIER 3: Daily summaries (requires all events for that day)
                SELECT 
                    s.id,
                    'summary'::text as item_type,
                    COALESCE(s.title, 'Daily Summary') as title,
                    NULL as document_type,
                    s.summary_type,
                    s.period_end as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    NULL::integer as source_id,
                    3 as priority_tier,
                    0 as retry_count,
                    NULL::timestamp as summary_priority
                FROM summaries s
                WHERE s.summary_type = 'daily'
                  AND s.status IN ('pending', 'stale')
                  AND s.period_end >= NOW() - INTERVAL '1 day' * $1
                  -- All events in this period must have summaries
                  AND NOT EXISTS (
                      SELECT 1 FROM events e
                      WHERE e.start_time >= s.period_start
                        AND e.start_time < s.period_end
                        AND (e.ai_summary IS NULL OR e.ai_summary = '')
                  )
                
                UNION ALL
                
                -- TIER 4: Weekly summaries (requires all daily summaries in that week)
                SELECT 
                    s.id,
                    'summary'::text as item_type,
                    COALESCE(s.title, 'Weekly Summary') as title,
                    NULL as document_type,
                    s.summary_type,
                    s.period_end as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    NULL::integer as source_id,
                    4 as priority_tier,
                    0 as retry_count,
                    NULL::timestamp as summary_priority
                FROM summaries s
                WHERE s.summary_type = 'weekly'
                  AND s.status IN ('pending', 'stale')
                  AND s.period_end >= NOW() - INTERVAL '1 day' * $1
                  -- All daily summaries in this period must be complete
                  AND NOT EXISTS (
                      SELECT 1 FROM summaries ds
                      WHERE ds.summary_type = 'daily'
                        AND ds.period_start >= s.period_start
                        AND ds.period_end <= s.period_end
                        AND ds.status IN ('pending', 'stale')
                  )
                
                UNION ALL
                
                -- TIER 5: Monthly summaries (requires all weekly summaries in that month)
                SELECT 
                    s.id,
                    'summary'::text as item_type,
                    COALESCE(s.title, 'Monthly Summary') as title,
                    NULL as document_type,
                    s.summary_type,
                    s.period_end as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    NULL::integer as source_id,
                    5 as priority_tier,
                    0 as retry_count,
                    NULL::timestamp as summary_priority
                FROM summaries s
                WHERE s.summary_type = 'monthly'
                  AND s.status IN ('pending', 'stale')
                  AND s.period_end >= NOW() - INTERVAL '1 day' * $1
                  -- All weekly summaries in this period must be complete
                  AND NOT EXISTS (
                      SELECT 1 FROM summaries ws
                      WHERE ws.summary_type = 'weekly'
                        AND ws.period_start >= s.period_start
                        AND ws.period_end <= s.period_end
                        AND ws.status IN ('pending', 'stale')
                  )
                
                UNION ALL
                
                -- TIER 6: Quarterly summaries (requires all monthly summaries in that quarter)
                SELECT 
                    s.id,
                    'summary'::text as item_type,
                    COALESCE(s.title, 'Quarterly Summary') as title,
                    NULL as document_type,
                    s.summary_type,
                    s.period_end as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    NULL::integer as source_id,
                    6 as priority_tier,
                    0 as retry_count,
                    NULL::timestamp as summary_priority
                FROM summaries s
                WHERE s.summary_type = 'quarterly'
                  AND s.status IN ('pending', 'stale')
                  AND s.period_end >= NOW() - INTERVAL '1 day' * $1
                  -- All monthly summaries in this period must be complete
                  AND NOT EXISTS (
                      SELECT 1 FROM summaries ms
                      WHERE ms.summary_type = 'monthly'
                        AND ms.period_start >= s.period_start
                        AND ms.period_end <= s.period_end
                        AND ms.status IN ('pending', 'stale')
                  )
                
                UNION ALL
                
                -- TIER 7: Annual summaries (requires all quarterly summaries in that year)
                SELECT 
                    s.id,
                    'summary'::text as item_type,
                    COALESCE(s.title, 'Annual Summary') as title,
                    NULL as document_type,
                    s.summary_type,
                    s.period_end as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    NULL::integer as source_id,
                    7 as priority_tier,
                    0 as retry_count,
                    NULL::timestamp as summary_priority
                FROM summaries s
                WHERE s.summary_type = 'annual'
                  AND s.status IN ('pending', 'stale')
                  AND s.period_end >= NOW() - INTERVAL '1 day' * $1
                  -- All quarterly summaries in this period must be complete
                  AND NOT EXISTS (
                      SELECT 1 FROM summaries qs
                      WHERE qs.summary_type = 'quarterly'
                        AND qs.period_start >= s.period_start
                        AND qs.period_end <= s.period_end
                        AND qs.status IN ('pending', 'stale')
                  )
            ) AS unified_queue
            ORDER BY 
                -- Manual priority boost (admin-triggered) comes first
                CASE WHEN summary_priority IS NOT NULL THEN 0 ELSE 1 END,
                summary_priority DESC NULLS LAST,
                -- Then order by DATE (newest first) - this ensures we complete all items
                -- for one date before moving to the next
                DATE(item_date) DESC NULLS LAST,
                -- Within the same date, order by tier:
                -- Tier 1 = docs/videos, Tier 2 = events, Tier 3 = daily, 
                -- Tier 4 = weekly, Tier 5 = monthly, Tier 6 = quarterly, Tier 7 = annual
                priority_tier ASC,
                -- Within same tier, fewer retries first
                retry_count ASC,
                -- Finally by time within the date (newest first)
                item_date DESC NULLS LAST
            LIMIT $2
        """, effective_max_age, self.ai_batch_size)
    
    async def _process_document(self, conn, item: dict) -> bool:
        """Queue a document for AI processing via MCP server.
        
        Fire-and-forget: sends request to MCP and moves on.
        MCP handles: ai_pending -> ai_processing -> completed (and DB updates).
        """
        doc_id = item['id']
        title = item['title']
        source_id = item.get('source_id')
        
        try:
            # Fire request to MCP - don't wait for AI completion
            # MCP will mark as ai_processing and update DB when done
            response = await self._http_client.post(
                f"{self.mcp_url}/process_document",
                json={
                    "document_id": doc_id,
                    "content": item.get('content_markdown'),
                    "title": title,
                    "document_type": item.get('document_type'),
                    "source_id": source_id,
                },
                timeout=10.0  # Quick timeout - just queuing
            )
            
            if response.status_code == 202:  # Accepted
                logger.info(f"Queued document {doc_id} for AI: {title[:50]}...")
                return True
            else:
                logger.warning(f"MCP rejected document {doc_id}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"Failed to queue document {doc_id}: {e}")
            return False
    
    async def _link_document_to_event(
        self, conn, doc_id: int, title: str, doc_type: str,
        source_id: int, city_id: str, metadata: dict
    ) -> bool:
        """
        Link a document to an event using AI-extracted metadata.
        
        Uses meeting_date, meeting_body, and meeting_type to find or create
        the appropriate event.
        """
        meeting_date = metadata.get("meeting_date")
        meeting_body = metadata.get("meeting_body")
        meeting_type = metadata.get("meeting_type")
        meeting_time = metadata.get("meeting_time")
        meeting_location = metadata.get("meeting_location")
        confidence = metadata.get("confidence", 0.0)
        
        if not meeting_date:
            logger.debug(f"No meeting date extracted for document {doc_id}, skipping linking")
            return False
        
        try:
            # Parse the meeting date
            from datetime import datetime
            meeting_dt = datetime.strptime(meeting_date, "%Y-%m-%d")
            
            # Try to find matching event by date and source
            event = await conn.fetchrow("""
                SELECT e.id, e.title, e.start_time
                FROM events e
                JOIN event_sources es ON e.id = es.event_id
                WHERE es.source_id = $1
                  AND DATE(e.start_time) = $2
                ORDER BY e.start_time DESC
                LIMIT 1
            """, source_id, meeting_dt.date())
            
            if not event:
                # Try to find by date and city (for videos that may span sources)
                event = await conn.fetchrow("""
                    SELECT e.id, e.title, e.start_time
                    FROM events e
                    JOIN event_sources es ON e.id = es.event_id
                    JOIN sources s ON es.source_id = s.id
                    WHERE s.city_id = $1
                      AND DATE(e.start_time) = $2
                      AND (e.title ILIKE '%' || $3 || '%' OR $3 IS NULL)
                    ORDER BY e.start_time DESC
                    LIMIT 1
                """, city_id, meeting_dt.date(), meeting_body)
            
            if event:
                # Link to existing event
                event_id = event['id']
                relationship = doc_type or 'related'
                
                await conn.execute("""
                    INSERT INTO event_documents (event_id, document_id, relationship)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (event_id, document_id) DO NOTHING
                """, event_id, doc_id, relationship)
                
                await self._log_activity(
                    "success", "linking", "linked",
                    f"Linked '{title[:40]}...' to event '{event['title'][:40]}...'",
                    entity_type="document", entity_id=doc_id, entity_title=title
                )
                
                logger.info(f"Linked document {doc_id} to event {event_id}: {event['title'][:40]}")
                return True
            else:
                # Create new event if this is an agenda, minutes, or video
                if doc_type in ('agenda', 'minutes', 'video'):
                    event_id = await self._create_event_for_document(
                        conn, doc_id, title, doc_type, source_id, city_id,
                        meeting_dt, meeting_body, meeting_type, meeting_time, meeting_location
                    )
                    if event_id:
                        return True
                
                logger.debug(f"No matching event found for document {doc_id} on {meeting_date}")
                return False
                
        except Exception as e:
            logger.warning(f"Failed to link document {doc_id}: {e}")
            return False
    
    async def _create_event_for_document(
        self, conn, doc_id: int, doc_title: str, doc_type: str,
        source_id: int, city_id: str,
        meeting_dt, meeting_body: str, meeting_type: str,
        meeting_time: str, meeting_location: str
    ) -> int:
        """Create a new event from document metadata and link the document."""
        try:
            from datetime import datetime, time
            
            # Build event title from meeting body or document title
            if meeting_body:
                event_title = meeting_body
            else:
                # Clean document title to extract meeting name
                event_title = doc_title
                for suffix in [' - Agenda', ' - Minutes', ' Agenda', ' Minutes', ' - Video']:
                    if event_title.endswith(suffix):
                        event_title = event_title[:-len(suffix)]
                        break
            
            # Parse time if provided
            start_time = meeting_dt
            if meeting_time:
                try:
                    # Try various time formats
                    for fmt in ["%I:%M %p", "%H:%M", "%I:%M%p"]:
                        try:
                            parsed_time = datetime.strptime(meeting_time.strip(), fmt)
                            start_time = meeting_dt.replace(
                                hour=parsed_time.hour, minute=parsed_time.minute
                            )
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass
            
            # Determine category
            category = meeting_type or "meeting"
            
            # Create the event
            event_id = await conn.fetchval("""
                INSERT INTO events (title, start_time, category, location, created_at, updated_at)
                VALUES ($1, $2, $3, $4, NOW(), NOW())
                RETURNING id
            """, event_title, start_time, category, meeting_location)
            
            # Link event to source
            await conn.execute("""
                INSERT INTO event_sources (event_id, source_id, first_seen_at, last_seen_at)
                VALUES ($1, $2, NOW(), NOW())
                ON CONFLICT (event_id, source_id) DO NOTHING
            """, event_id, source_id)
            
            # Link document to event
            relationship = doc_type or 'related'
            await conn.execute("""
                INSERT INTO event_documents (event_id, document_id, relationship)
                VALUES ($1, $2, $3)
                ON CONFLICT (event_id, document_id) DO NOTHING
            """, event_id, doc_id, relationship)
            
            await self._log_activity(
                "success", "linking", "created",
                f"Created event '{event_title}' on {meeting_dt.date()} and linked '{doc_title[:30]}...'",
                entity_type="event", entity_id=event_id, entity_title=event_title
            )
            
            logger.info(f"Created event {event_id}: {event_title} on {meeting_dt.date()}")
            return event_id
            
        except Exception as e:
            logger.warning(f"Failed to create event for document {doc_id}: {e}")
            return None

    async def _process_video(self, conn, item: dict) -> bool:
        """Queue a video for AI processing via MCP server.
        
        Fire-and-forget: sends request to MCP and moves on.
        MCP handles: ai_pending -> ai_processing -> completed (and DB updates).
        Videos can take 10+ minutes so we definitely don't wait.
        """
        doc_id = item['id']
        title = item['title']
        source_id = item.get('source_id')
        
        try:
            # Fire request to MCP - don't wait for AI completion
            response = await self._http_client.post(
                f"{self.mcp_url}/process_video",
                json={
                    "document_id": doc_id,
                    "video_url": item.get('source_url'),
                    "title": title,
                    "source_id": source_id,
                },
                timeout=10.0  # Quick timeout - just queuing
            )
            
            if response.status_code == 202:  # Accepted
                logger.info(f"Queued video {doc_id} for AI: {title[:50]}...")
                return True
            else:
                logger.warning(f"MCP rejected video {doc_id}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"Failed to queue video {doc_id}: {e}")
            return False
    
    async def _process_event(self, conn, item: dict) -> bool:
        """Process an event summary via MCP server."""
        event_id = item['id']
        title = item['title']
        
        await self._log_activity(
            "info", "ai", "started",
            f"Event summary started: {title[:60]}...",
            entity_type="event", entity_id=event_id, entity_title=title
        )
        
        try:
            response = await self._http_client.post(
                f"{self.mcp_url}/summarize_event",
                json={"event_id": event_id}
            )
            
            if response.status_code == 200:
                result = response.json()
                summary = result.get("summary", "")
                
                if summary:
                    await conn.execute("""
                        UPDATE events 
                        SET ai_summary = $1, updated_at = NOW()
                        WHERE id = $2
                    """, summary, event_id)
                    
                    await self._log_activity(
                        "success", "ai", "completed",
                        f"Event summary generated: {title[:60]}... ({len(summary)} chars)",
                        entity_type="event", entity_id=event_id, entity_title=title
                    )
                    
                    logger.info(f"Generated summary for event {event_id}: {title[:50]}...")
                    return True
                else:
                    raise Exception("Empty summary returned")
            else:
                raise Exception(f"MCP server returned {response.status_code}")
                
        except Exception as e:
            logger.warning(f"Event {event_id} AI failed: {e}")
            
            await self._log_activity(
                "error", "ai", "failed",
                f"Event summary failed: {title[:60]}... - {str(e)[:100]}",
                entity_type="event", entity_id=event_id, entity_title=title
            )
            
            return False
    
    async def _process_summary(self, conn, item: dict) -> bool:
        """Process a period summary via MCP server."""
        summary_id = item['id']
        title = item['title']
        summary_type = item.get('summary_type', 'weekly')
        
        await self._log_activity(
            "info", "ai", "started",
            f"Period summary started: {title[:60]}...",
            entity_type="summary", entity_id=summary_id, entity_title=title
        )
        
        try:
            response = await self._http_client.post(
                f"{self.mcp_url}/generate_period_summary",
                json={
                    "summary_id": summary_id,
                    "summary_type": summary_type,
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                
                await self._log_activity(
                    "success", "ai", "completed",
                    f"Period summary generated: {title[:60]}...",
                    entity_type="summary", entity_id=summary_id, entity_title=title
                )
                
                logger.info(f"Generated period summary {summary_id}: {title[:50]}...")
                return True
            else:
                raise Exception(f"MCP server returned {response.status_code}")
                
        except Exception as e:
            logger.warning(f"Summary {summary_id} generation failed: {e}")
            
            await self._log_activity(
                "error", "ai", "failed",
                f"Period summary failed: {title[:60]}... - {str(e)[:100]}",
                entity_type="summary", entity_id=summary_id, entity_title=title
            )
            
            return False
    
    async def _mark_failed(self, conn, item: dict, error: str) -> None:
        """Mark an item as failed with error message."""
        item_type = item['item_type']
        item_id = item['id']
        
        if item_type in ('document', 'video'):
            await conn.execute("""
                UPDATE documents 
                SET retry_count = COALESCE(retry_count, 0) + 1,
                    error_message = $1,
                    updated_at = NOW()
                WHERE id = $2
            """, error[:500], item_id)
    
    async def _process_cascade_triggers(self) -> int:
        """
        Check for documents with new AI summaries that need cascade propagation.
        
        When a document gets a summary, we need to:
        1. Mark parent event summary as stale (if exists)
        2. Mark parent period summaries as stale
        """
        cascaded = 0
        
        async with self._db_pool.acquire() as conn:
            # Find documents with AI summaries that haven't triggered cascade
            docs = await conn.fetch("""
                SELECT 
                    d.id,
                    ed.event_id,
                    s.city_id
                FROM documents d
                JOIN event_documents ed ON d.id = ed.document_id
                JOIN sources s ON d.source_id = s.id
                WHERE d.ai_summary IS NOT NULL
                  AND d.ai_summary != ''
                  AND d.content_status = 'completed'
                  AND (d.cascade_triggered_at IS NULL 
                       OR d.cascade_triggered_at < d.ai_summary_updated_at)
                  AND d.ai_summary_updated_at > NOW() - INTERVAL '2 hours'
                ORDER BY d.ai_summary_updated_at DESC
                LIMIT 10
            """)
            
            if not docs:
                return 0
            
            logger.debug(f"Found {len(docs)} documents needing cascade")
            
            for doc in docs:
                try:
                    success = await self._trigger_cascade(
                        document_id=doc["id"],
                        event_id=doc["event_id"],
                        city_id=doc["city_id"],
                    )
                    
                    if success:
                        await conn.execute(
                            "UPDATE documents SET cascade_triggered_at = NOW() WHERE id = $1",
                            doc["id"]
                        )
                        cascaded += 1
                        logger.debug(f"Cascade triggered for document {doc['id']}")
                        
                except Exception as e:
                    logger.warning(f"Cascade failed for document {doc['id']}: {e}")
        
        return cascaded
    
    async def _trigger_cascade(
        self, document_id: int, event_id: int, city_id: str
    ) -> bool:
        """
        Call MCP server to trigger cascade for a document.
        
        This marks the event's summary as stale and any parent period summaries.
        """
        try:
            response = await self._http_client.post(
                f"{self.mcp_url}/trigger_cascade_for_document",
                params={
                    "document_id": document_id,
                    "event_id": event_id,
                    "city_id": city_id,
                },
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("success", False)
            else:
                logger.warning(f"Cascade endpoint returned {response.status_code}")
                return False
        
        except Exception as e:
            logger.error(f"Error calling cascade endpoint: {e}")
            return False


async def main():
    """Run cascade service."""
    import signal
    
    mcp_url = os.getenv("MCP_URL", "http://localhost:8000")
    db_url = os.getenv("DATABASE_URL")
    
    service = CascadeService(mcp_url=mcp_url, db_url=db_url)
    
    # Handle signals
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Signal received, stopping service...")
        asyncio.create_task(service.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())


