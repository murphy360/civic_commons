"""
AI Queue Processor - orchestrates AI analysis tasks.

Handles document summaries, event summaries, and coordination
between different AI processing phases.
"""

import logging
import os
from typing import Optional, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.activity_logger import ActivityLogger

logger = logging.getLogger("civic.ai_queue")

# Type alias for the cascade callback
CascadeCallback = Callable[[int, int, str], Awaitable[None]]


class AIQueueProcessor:
    """Processes the AI analysis queue in priority order."""

    def __init__(self, db_pool, doc_summarizer, ai_processor, document_linker, settings,
                 queue_manager=None,
                 on_document_processed: Optional[CascadeCallback] = None,
                 activity_logger: Optional["ActivityLogger"] = None):
        self.db_pool = db_pool
        self.doc_summarizer = doc_summarizer
        self.ai_processor = ai_processor
        self.document_linker = document_linker
        self.settings = settings
        self.queue_manager = queue_manager
        self._on_document_processed = on_document_processed
        self.activity = activity_logger

    async def process_queue(self) -> None:
        """
        Process documents, events, and summaries that need AI analysis.
        
        Uses a unified date-based approach - most recent items first,
        regardless of type. Documents, events, and summaries are all
        processed together in date order.
        """
        batch_size = self.settings.ai_queue_batch_size
        logger.info("AI analysis queue: Starting processing run...")

        if not self.doc_summarizer or not self.doc_summarizer.enabled:
            logger.debug("AI analysis queue: Summarizer not enabled, skipping")
            return

        try:
            async with self.db_pool.acquire() as conn:
                # Still do date-based linking first (fast, no AI)
                await self.document_linker.process_date_based_linking(conn)

                # Process unified queue - documents, events, and summaries by date
                await self._process_unified_queue(conn, batch_size)

            logger.info("AI analysis queue: Processing run complete")

        except Exception as e:
            logger.error(f"AI analysis queue error: {e}")

    async def _process_unified_queue(self, conn, batch_size: int) -> None:
        """
        Process all pending items (documents, events, summaries) with proper
        dependency ordering:
        
        1. PDF Documents (extracted) - highest priority
        2. Videos - same tier as documents
        3. Events - only when ALL linked documents have AI summaries
        4. Summaries - only when events in period are summarized
        """
        max_age_days = int(os.getenv("AI_SUMMARY_MAX_AGE_DAYS", "365"))
        
        # Use queue_manager for proper dependency-aware ordering
        if self.queue_manager:
            items = await self.queue_manager.get_ai_queue(conn, limit=batch_size, max_age_days=max_age_days)
        else:
            # Fallback to simple query if no queue_manager
            logger.warning("AI queue: No queue_manager, using fallback query")
            items = await conn.fetch("""
                SELECT 
                    id,
                    'document'::text as item_type,
                    title,
                    document_type,
                    NULL::varchar as summary_type,
                    COALESCE(meeting_date, created_at) as item_date,
                    content_markdown,
                    local_path,
                    source_url
                FROM documents
                WHERE (ai_summary IS NULL OR ai_summary = '')
                  AND content_status IN ('extracted', 'ai_pending')
                  AND content_markdown IS NOT NULL
                ORDER BY meeting_date DESC NULLS LAST
                LIMIT $1
            """, batch_size)

        if not items:
            logger.debug("AI analysis queue: No items pending")
            return

        # Log what we're processing
        item_types = {}
        for item in items:
            t = item['item_type']
            item_types[t] = item_types.get(t, 0) + 1
        logger.info(f"AI analysis queue: Processing {len(items)} items from unified queue ({item_types})")

        for item in items:
            try:
                item_type = item['item_type']
                logger.debug(f"AI queue: Processing {item_type} '{item['title']}'")
                if item_type == 'document':
                    await self._process_single_document_summary(conn, dict(item))
                elif item_type == 'video':
                    # Videos are processed as documents but with transcription
                    await self._process_single_document_summary(conn, dict(item))
                elif item_type == 'event':
                    await self._process_single_event_summary(conn, dict(item))
                elif item_type == 'summary':
                    await self._process_single_summary(conn, dict(item))
            except Exception as e:
                logger.warning(f"Failed to process {item['item_type']} '{item['title']}': {e}")

    async def _process_document_summaries(self, conn, batch_size: int) -> None:
        """Generate AI summaries for documents that don't have them."""
        max_age_days = self.settings.ai_summary_max_age_days
        age_filter = ""
        if max_age_days > 0:
            age_filter = f"""AND (
                meeting_date >= NOW() - INTERVAL '{max_age_days} days'
                OR meeting_date IS NULL
            )"""

        docs = await conn.fetch(f"""
            SELECT id, title, document_type, content_markdown, local_path, source_url, linking_status, meeting_date
            FROM documents
            WHERE (ai_summary IS NULL OR ai_summary = '')
              AND (local_path IS NOT NULL OR (document_type = 'video' AND source_url LIKE '%youtu%'))
              {age_filter}
            ORDER BY 
                summary_priority DESC NULLS LAST,
                -- Prioritize: 1) current year docs, 2) current year legislation, 3) older legislation, 4) older docs
                CASE 
                    WHEN meeting_date >= DATE_TRUNC('year', NOW()) THEN 0  -- Current year with date
                    WHEN document_type IN ('ordinance', 'resolution') AND title ~ '-25[^0-9]' THEN 1  -- 2025 legislation
                    WHEN document_type IN ('ordinance', 'resolution') THEN 2  -- Other legislation
                    WHEN meeting_date IS NOT NULL THEN 3  -- Has date but older
                    ELSE 4  -- No date
                END,
                meeting_date DESC NULLS LAST,
                CASE WHEN linking_status = 'needs_summary' THEN 0 ELSE 1 END,
                CASE 
                    WHEN local_path IS NOT NULL THEN 0 
                    WHEN document_type = 'video' AND source_url LIKE '%youtu%' THEN 1
                    ELSE 2 
                END,
                created_at DESC
            LIMIT $1
        """, batch_size)

        if not docs:
            logger.debug("AI analysis queue: No documents pending summaries")
            return

        logger.info(f"AI analysis queue: Processing {len(docs)} document summaries")

        for doc in docs:
            await self._process_single_document_summary(conn, doc)

    async def _process_single_document_summary(self, conn, doc: dict) -> None:
        """Process a single document for AI summary."""
        MAX_AI_RETRIES = 3
        
        # Log AI started
        if self.activity:
            source_name = await conn.fetchval("""
                SELECT s.name FROM sources s WHERE s.id = $1
            """, doc.get("source_id"))
            await self.activity.log_ai_started(
                "document", doc["id"], doc["title"],
                source_name=source_name,
            )
        
        try:
            # Check current retry count
            current_retries = doc.get("retry_count", 0) or 0
            
            # Check for YouTube video
            video_url = None
            if doc["document_type"] == "video" and doc["source_url"]:
                url = doc["source_url"]
                if "youtu.be" in url or "youtube.com" in url:
                    video_url = url

            # Validate metadata for uncertain types
            validated_type = doc["document_type"]
            if doc["document_type"] in ("other", None) and not video_url:
                metadata = await self.doc_summarizer.validate_metadata(
                    title=doc["title"],
                    current_document_type=doc["document_type"],
                    content_text=doc["content_markdown"],
                    local_path=doc["local_path"],
                )
                if metadata and metadata.get("confidence") in ("high", "medium"):
                    new_type = metadata.get("document_type")
                    if new_type and new_type != doc["document_type"]:
                        validated_type = new_type
                        await conn.execute("""
                            UPDATE documents SET document_type = $1 WHERE id = $2
                        """, validated_type, doc["id"])
                        logger.info(f"Corrected document type for '{doc['title']}': {doc['document_type']} -> {validated_type}")

            result = await self.doc_summarizer.generate_summary(
                title=doc["title"],
                document_type=validated_type,
                content_text=doc["content_markdown"],
                local_path=doc["local_path"],
                video_url=video_url,
            )

            if result:
                await self.db_pool.update_document_ai_summary(
                    conn, doc["id"], 
                    ai_summary=result.text_with_footer,
                    model_used=result.model_name,
                )
                logger.info(f"AI summary generated for '{doc['title']}' using {result.model_name}")
                
                # Log AI completed
                if self.activity:
                    await self.activity.log_ai_completed(
                        "document", doc["id"], doc["title"],
                        summary_length=len(result.text_with_footer),
                        model_used=result.model_name,
                        source_name=source_name if 'source_name' in dir() else None,
                    )

                # Trigger cascade update if callback is set
                if self._on_document_processed:
                    event_id = await conn.fetchval("""
                        SELECT event_id FROM event_documents WHERE document_id = $1 LIMIT 1
                    """, doc["id"])
                    if event_id:
                        city_id = await conn.fetchval("""
                            SELECT city_id FROM sources s
                            JOIN documents d ON d.source_id = s.id
                            WHERE d.id = $1
                        """, doc["id"])
                        if city_id:
                            await self._on_document_processed(doc["id"], event_id, city_id)

                # Extract meeting metadata (date, time, location) from agenda/minutes
                await self._extract_meeting_metadata(conn, doc, validated_type)
                
                # Extract legislation mentions (non-video only)
                if validated_type != "video":
                    await self._extract_legislation(conn, doc, validated_type)

                # Reset linking status if needed
                if doc.get("linking_status") == "needs_summary":
                    await conn.execute("""
                        UPDATE documents SET linking_status = 'pending' WHERE id = $1
                    """, doc["id"])
            else:
                # Mark as failed with a special marker so we don't retry forever
                # Use a special value that indicates permanent failure
                await conn.execute("""
                    UPDATE documents 
                    SET ai_summary = '[AI_SUMMARY_FAILED]',
                        content_status = 'failed',
                        error_message = 'AI summary generation returned no result'
                    WHERE id = $1
                """, doc["id"])
                logger.warning(f"Marked document '{doc['title']}' as AI summary failed (no result)")
                
                # Log AI failed
                if self.activity:
                    await self.activity.log_ai_failed(
                        "document", doc["id"], doc["title"],
                        "AI summary generation returned no result",
                    )

        except Exception as e:
            # Increment retry count
            new_retry_count = (doc.get("retry_count", 0) or 0) + 1
            error_msg = str(e)[:500]  # Truncate long error messages
            
            if new_retry_count >= MAX_AI_RETRIES:
                # Max retries reached - mark as permanently failed
                await conn.execute("""
                    UPDATE documents 
                    SET ai_summary = '[AI_SUMMARY_FAILED]',
                        content_status = 'failed',
                        retry_count = $2,
                        error_message = $3
                    WHERE id = $1
                """, doc["id"], new_retry_count, f"AI failed after {MAX_AI_RETRIES} attempts: {error_msg}")
                logger.error(f"AI analysis permanently failed for '{doc['title']}' after {MAX_AI_RETRIES} attempts: {e}")
                
                # Log AI failed (permanent)
                if self.activity:
                    await self.activity.log_ai_failed(
                        "document", doc["id"], doc["title"],
                        f"Failed after {MAX_AI_RETRIES} attempts: {error_msg}",
                    )
            else:
                # Increment retry count but keep in queue
                await conn.execute("""
                    UPDATE documents 
                    SET retry_count = $2,
                        error_message = $3
                    WHERE id = $1
                """, doc["id"], new_retry_count, f"AI attempt {new_retry_count} failed: {error_msg}")
                logger.warning(f"AI analysis failed for '{doc['title']}' (attempt {new_retry_count}/{MAX_AI_RETRIES}): {e}")

    async def _process_single_event_summary(self, conn, item: dict) -> None:
        """Process a single event for AI summary from unified queue."""
        event_id = item["id"]
        
        # Check if event has linked documents with summaries
        doc_count = await conn.fetchval("""
            SELECT COUNT(*) FROM event_documents ed
            JOIN documents d ON ed.document_id = d.id
            WHERE ed.event_id = $1 
              AND d.ai_summary IS NOT NULL 
              AND d.ai_summary != ''
              AND d.ai_summary != '[AI_SUMMARY_FAILED]'
        """, event_id)
        
        if doc_count == 0:
            logger.debug(f"Event '{item['title']}' has no summarized documents yet, skipping")
            return
        
        await self.generate_event_summary(conn, event_id)

    async def _process_single_summary(self, conn, item: dict) -> None:
        """Process a single period summary (weekly/monthly/quarterly/annual) from unified queue."""
        from .ai.cascade import SummaryCascadeManager, SummaryType
        
        summary_id = item["id"]
        summary_type_str = item["summary_type"]
        
        try:
            # Get the full summary record with city name
            summary = await conn.fetchrow("""
                SELECT s.id, s.city_id, s.summary_type, s.period_start, s.period_end, 
                       s.status, s.event_id, c.display_name as city_name
                FROM summaries s
                JOIN cities c ON s.city_id = c.city_id
                WHERE s.id = $1
            """, summary_id)
            
            if not summary:
                return
            
            # Map string type to enum
            type_map = {
                'event': SummaryType.EVENT,
                'daily': SummaryType.DAILY,
                'weekly': SummaryType.WEEKLY,
                'monthly': SummaryType.MONTHLY,
                'quarterly': SummaryType.QUARTERLY,
                'annual': SummaryType.ANNUAL,
            }
            summary_type = type_map.get(summary_type_str)
            if not summary_type:
                logger.warning(f"Unknown summary type: {summary_type_str}")
                return
            
            # Use cascade system to regenerate the summary
            cascade = SummaryCascadeManager(self.db_pool, self.ai_processor)
            await cascade._regenerate_summary(conn, summary, summary_type)
            
            logger.info(f"Generated {summary_type_str} summary for period ending {item['item_date']}")
            
        except Exception as e:
            logger.warning(f"Failed to generate {summary_type_str} summary: {e}")
            # Mark as failed
            await conn.execute("""
                UPDATE summaries SET status = 'failed', error_message = $2 WHERE id = $1
            """, summary_id, str(e)[:500])

    async def _extract_meeting_metadata(self, conn, doc: dict, doc_type: str) -> None:
        """
        Extract meeting metadata (date, time, location) from document and update linked event.
        
        Only applies to meeting documents (agendas, minutes) and only updates events
        that have placeholder values (midnight time, no location).
        """
        # Only process agendas and minutes - they contain meeting details
        if doc_type not in ("agenda", "minutes", "packet"):
            return
        
        try:
            metadata = await self.doc_summarizer.extract_meeting_metadata(
                title=doc["title"],
                document_type=doc_type,
                content_text=doc["content_markdown"],
                local_path=doc["local_path"],
            )
            
            if not metadata:
                return
            
            # Find the linked event
            event_id = await conn.fetchval("""
                SELECT event_id FROM event_documents WHERE document_id = $1 LIMIT 1
            """, doc["id"])
            
            if not event_id:
                logger.debug(f"No linked event for document '{doc['title']}' - skipping metadata update")
                return
            
            # Update the event with extracted metadata
            updated = await self.db_pool.update_event_from_document_metadata(
                conn, event_id, metadata
            )
            
            if updated:
                logger.info(f"Updated event {event_id} with metadata from '{doc['title']}'")
                
        except Exception as e:
            logger.warning(f"Meeting metadata extraction failed for '{doc['title']}': {e}")

    async def _extract_legislation(self, conn, doc: dict, doc_type: str) -> None:
        """Extract and store legislation mentions from a document."""
        try:
            legislation_list = await self.doc_summarizer.extract_legislation(
                title=doc["title"],
                document_type=doc_type,
                content_text=doc["content_markdown"],
                local_path=doc["local_path"],
            )

            # legislation_list will be [] on parse failure, [] if no legislation found
            # Only log if we have actual results
            if legislation_list:
                logger.info(f"Extracted {len(legislation_list)} legislation mentions from '{doc['title']}'")

            event_id = await conn.fetchval("""
                SELECT event_id FROM event_documents WHERE document_id = $1 LIMIT 1
            """, doc["id"])

            doc_row = await conn.fetchrow("""
                SELECT meeting_date FROM documents WHERE id = $1
            """, doc["id"])
            mentioned_date = doc_row["meeting_date"] if doc_row else None

            for legis in legislation_list:
                await self._store_legislation_mention(conn, doc["id"], event_id, mentioned_date, legis)

        except Exception as e:
            logger.warning(f"Legislation extraction failed for '{doc['title']}': {e}")

    async def _store_legislation_mention(self, conn, doc_id: int, event_id: Optional[int],
                                         mentioned_date, legis: dict) -> None:
        """Store a single legislation mention."""
        try:
            legis_type = (legis.get("type") or "").lower().strip()
            legis_number = (legis.get("number") or "").strip()
            legis_title = (legis.get("title") or "").strip() or None
            action = (legis.get("action") or "discussed").lower().strip()
            vote_result = (legis.get("vote_result") or "").strip() or None
            vote_details = (legis.get("vote_details") or "").strip() or None
            excerpt = (legis.get("excerpt") or "").strip() or None

            if not legis_type or not legis_number:
                return

            existing = await conn.fetchrow("""
                SELECT id FROM legislation_mentions
                WHERE document_id = $1 AND legislation_number = $2 AND action_taken = $3
            """, doc_id, legis_number, action)

            if existing:
                await conn.execute("""
                    UPDATE legislation_mentions
                    SET legislation_title = COALESCE($2, legislation_title),
                        vote_result = COALESCE($3, vote_result),
                        vote_details = COALESCE($4, vote_details),
                        excerpt = COALESCE($5, excerpt),
                        event_id = COALESCE($6, event_id),
                        updated_at = NOW()
                    WHERE id = $1
                """, existing["id"], legis_title, vote_result, vote_details, excerpt, event_id)
            else:
                await conn.execute("""
                    INSERT INTO legislation_mentions (
                        document_id, event_id, legislation_type, legislation_number,
                        legislation_title, action_taken, vote_result, vote_details,
                        excerpt, mentioned_date
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """, doc_id, event_id, legis_type, legis_number, legis_title,
                    action, vote_result, vote_details, excerpt, mentioned_date)

        except Exception as e:
            logger.warning(f"Failed to store legislation mention: {e}")

    async def _process_event_summaries(self, conn, batch_size: int) -> None:
        """Generate AI summaries for events with linked documents."""
        max_age_days = self.settings.ai_summary_max_age_days
        age_filter = ""
        if max_age_days > 0:
            age_filter = f"AND e.start_time >= NOW() - INTERVAL '{max_age_days} days'"

        events = await conn.fetch(f"""
            SELECT DISTINCT e.id, e.title, e.start_time, e.category
            FROM events e
            JOIN event_documents ed ON e.id = ed.event_id
            JOIN documents d ON ed.document_id = d.id
            WHERE e.ai_summary IS NULL
              AND d.ai_summary IS NOT NULL AND d.ai_summary != ''
              AND ed.relationship NOT IN ('none', 'unlinked')
              {age_filter}
            ORDER BY e.start_time DESC NULLS LAST
            LIMIT $1
        """, batch_size)

        if not events:
            logger.debug("AI analysis queue: No events pending summaries")
            return

        logger.info(f"AI analysis queue: Processing {len(events)} event summaries")

        for event in events:
            await self.generate_event_summary(conn, event["id"])

    async def generate_event_summary(self, conn, event_id: int) -> None:
        """Generate or update the AI summary for an event."""
        if not self.ai_processor or not self.ai_processor.enabled:
            return

        try:
            event_row = await conn.fetchrow("""
                SELECT id, title, description, start_time, location, category
                FROM events WHERE id = $1
            """, event_id)

            if not event_row:
                return

            event = {
                'id': event_row['id'],
                'title': event_row['title'],
                'description': event_row['description'],
                'start_time': event_row['start_time'].isoformat() if event_row['start_time'] else None,
                'location': event_row['location'],
                'category': event_row['category'],
            }

            source_rows = await conn.fetch("""
                SELECT s.name, es.raw_data
                FROM event_sources es
                JOIN sources s ON es.source_id = s.id
                WHERE es.event_id = $1
            """, event_id)

            sources = [{'name': r['name'], 'raw_data': r['raw_data']} for r in source_rows]

            doc_rows = await conn.fetch("""
                SELECT d.id, d.title, d.document_type, ed.relationship,
                       d.content_text, d.local_path, d.ai_summary
                FROM event_documents ed
                JOIN documents d ON ed.document_id = d.id
                WHERE ed.event_id = $1
            """, event_id)

            documents = [
                {
                    'id': d['id'], 'title': d['title'], 'document_type': d['document_type'],
                    'relationship': d['relationship'], 'content_text': d['content_text'],
                    'local_path': d['local_path'], 'ai_summary': d['ai_summary'],
                }
                for d in doc_rows
            ]

            summary = await self.ai_processor.generate_event_summary(
                event=event, sources=sources, documents=documents
            )

            if summary:
                await conn.execute("""
                    UPDATE events SET ai_summary = $1, ai_summary_updated_at = NOW() WHERE id = $2
                """, summary, event_id)
                logger.info(f"Generated AI summary for event '{event['title']}'")

        except Exception as e:
            logger.warning(f"Failed to generate AI summary for event {event_id}: {e}")

    async def get_queue_status(self, conn) -> dict:
        """Get comprehensive status of the AI queue."""
        status = {
            "pending_linking": await self.document_linker.get_date_linkable_count(conn),
            "pending_ai_linking": await self.document_linker.get_ai_linkable_count(conn),
        }

        max_age_days = self.settings.ai_summary_max_age_days
        age_filter = ""
        if max_age_days > 0:
            age_filter = f"AND (d.meeting_date >= NOW() - INTERVAL '{max_age_days} days' OR d.meeting_date IS NULL)"

        status["pending_doc_summaries"] = await conn.fetchval(f"""
            SELECT COUNT(*) FROM documents d
            WHERE (d.ai_summary IS NULL OR d.ai_summary = '')
              AND (d.local_path IS NOT NULL OR (d.document_type = 'video' AND d.source_url LIKE '%youtu%'))
              {age_filter}
        """)

        status["pending_event_summaries"] = await conn.fetchval("""
            SELECT COUNT(*) FROM events e
            JOIN event_documents ed ON e.id = ed.event_id
            JOIN documents d ON ed.document_id = d.id
            WHERE e.ai_summary IS NULL
              AND d.ai_summary IS NOT NULL AND d.ai_summary != ''
        """)

        return status

    async def is_busy(self) -> bool:
        """Check if AI queue has significant pending work."""
        async with self.db_pool.acquire() as conn:
            status = await self.get_queue_status(conn)
            total = (status.get("pending_linking", 0) +
                     status.get("pending_ai_linking", 0) +
                     status.get("pending_doc_summaries", 0))
            return total > 10
