"""
Purpose: Main entrypoint for the scraper worker service
Dependencies: asyncio, APScheduler for cron scheduling, config module for YAML loading
Consumed by: Docker container entrypoint, direct execution for development
Side effects: Schedules and executes scraping jobs, writes to PostgreSQL
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import load_all_configs, Settings
from drivers import get_driver
from models import Event, Document
from pipeline.storage import DatabasePool
from pipeline.ai_processor import AIEventProcessor
from pipeline.ai import DocumentSummarizer, GeminiClient
from pipeline.ai.newsletter import NewsletterGenerator, PeriodType, get_period_dates, generate_newsletter_title
from pipeline.backfill import BackfillManager
from pipeline.downloader import DocumentDownloader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("civic.worker")


class Worker:
    """
    Main worker class that manages the scraping scheduler.
    
    Responsibilities:
    - Load city configurations from /configs
    - Schedule scraping jobs based on cron expressions
    - Execute drivers and store results
    - Handle graceful shutdown
    - Optionally enrich events with AI
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        # Configure scheduler with longer misfire grace time for async jobs
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                'coalesce': True,  # Combine multiple missed runs into one
                'max_instances': 1,  # Only run one instance at a time
                'misfire_grace_time': 300,  # Allow 5 min grace for missed jobs
            }
        )
        self.db_pool: DatabasePool | None = None
        self.ai_processor: Optional[AIEventProcessor] = None
        self.doc_summarizer: Optional[DocumentSummarizer] = None
        self.newsletter_generator: Optional[NewsletterGenerator] = None
        self.backfill_manager: Optional[BackfillManager] = None
        self.document_downloader: Optional[DocumentDownloader] = None
        self._shutdown_event = asyncio.Event()
        self._configs: list = []  # Store configs for backfill access

    async def initialize(self) -> None:
        """Initialize database connection pool and optional AI processor."""
        logger.info("Initializing database connection pool...")
        self.db_pool = await DatabasePool.create(self.settings.get_database_url())
        
        # Initialize document downloader
        download_dir = os.getenv("DOCUMENT_STORAGE_DIR", "/data/documents")
        self.document_downloader = DocumentDownloader(storage_dir=Path(download_dir))
        logger.info(f"Document downloader initialized (storage: {download_dir})")
        
        # Initialize AI processor if API key is available
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
        if gemini_key:
            self.ai_processor = AIEventProcessor(api_key=gemini_key)
            # Create a separate document summarizer using the same client
            gemini_client = GeminiClient(api_key=gemini_key)
            self.doc_summarizer = DocumentSummarizer(gemini_client)
            # Create newsletter generator
            self.newsletter_generator = NewsletterGenerator(gemini_client)
            logger.info("AI event processor, document summarizer, and newsletter generator enabled")
        else:
            logger.info("AI processing disabled (no GEMINI_API_KEY)")
        
        # Initialize backfill manager
        backfill_months = int(os.getenv("BACKFILL_MONTHS", "12"))
        backfill_delay = int(os.getenv("BACKFILL_DELAY_SECONDS", "300"))
        initial_days_back = int(os.getenv("INITIAL_DAYS_BACK", "7"))
        
        self.backfill_manager = BackfillManager(
            db_pool=self.db_pool,
            initial_days_back=initial_days_back,
            backfill_months=backfill_months,
            batch_delay_seconds=backfill_delay,
        )
        
        # Ensure backfill tables exist
        async with self.db_pool.acquire() as conn:
            await self.backfill_manager.ensure_tables_exist(conn)
        
        logger.info(
            f"Backfill manager initialized (initial: {initial_days_back} days, "
            f"backfill: {backfill_months} months, delay: {backfill_delay}s)"
        )
    
    async def _enrich_event_with_ai(self, event: Event, city_name: str = "") -> Event:
        """
        Use AI to validate and enrich an event.
        
        Args:
            event: The event to enrich
            city_name: Name of the city for location context
        
        Returns the original or enriched event.
        """
        if not self.ai_processor:
            return event
            
        try:
            # Use AI to normalize the event (clean title, description, categorize)
            source_context = f"City: {city_name}" if city_name else ""
            enriched = await self.ai_processor.normalize_event(event, source_context)
            
            # Also validate for quality issues
            is_valid, issues = await self.ai_processor.validate_event(enriched)
            if not is_valid and issues:
                logger.warning(
                    f"AI found quality issues in '{event.title}': {issues}"
                )
                    
            return enriched
            
        except Exception as e:
            logger.warning(f"AI enrichment failed for '{event.title}': {e}")
            return event  # Return original on failure
        logger.info("Database pool initialized")

    async def shutdown(self) -> None:
        """Graceful shutdown of all resources."""
        logger.info("Shutting down worker...")
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if self.backfill_manager:
            await self.backfill_manager.stop()
        if self.ai_processor:
            await self.ai_processor.close()
        if self.db_pool:
            await self.db_pool.close()
        logger.info("Worker shutdown complete")

    def schedule_sources(self, configs: list) -> None:
        """
        Schedule all sources from loaded configurations.
        
        Args:
            configs: List of loaded city configurations
        """
        # Store configs for manual trigger lookup
        self._configs = configs
        
        for config in configs:
            city_name = config.city_profile.name
            
            for source in config.sources:
                # Skip disabled sources
                if not source.enabled:
                    logger.info(f"Skipping disabled source: {city_name}:{source.name}")
                    continue
                    
                job_id = f"{city_name}:{source.name}"
                
                # Parse cron expression
                cron_parts = source.schedule.split()
                trigger = CronTrigger(
                    minute=cron_parts[0],
                    hour=cron_parts[1],
                    day=cron_parts[2],
                    month=cron_parts[3],
                    day_of_week=cron_parts[4],
                    timezone=config.city_profile.timezone,
                )

                self.scheduler.add_job(
                    self.scrape_source,
                    trigger=trigger,
                    id=job_id,
                    name=f"Scrape {source.name} for {city_name}",
                    kwargs={
                        "config": config,
                        "source": source,
                    },
                    replace_existing=True,
                )
                logger.info(f"Scheduled job: {job_id} ({source.schedule})")

        # Schedule background AI analysis job using config values
        if self.doc_summarizer and self.doc_summarizer.enabled:
            interval = self.settings.ai_queue_interval_seconds
            self.scheduler.add_job(
                self.process_ai_analysis_queue,
                trigger=CronTrigger(second=f"*/{interval}") if interval < 60 else CronTrigger(minute=f"*/{interval // 60}"),
                id="ai_analysis_queue",
                name="Process AI Analysis Queue",
                replace_existing=True,
            )
            logger.info(f"Scheduled AI analysis queue processor (every {interval} seconds, {self.settings.ai_queue_batch_size} items per batch)")

        # Schedule manual trigger checker (every 15 seconds)
        self.scheduler.add_job(
            self.process_manual_triggers,
            trigger=CronTrigger(second="*/15"),
            id="manual_trigger_checker",
            name="Check Manual Scrape Triggers",
            replace_existing=True,
        )
        logger.info("Scheduled manual trigger checker (every 15 seconds)")

        # Schedule newsletter generation jobs if AI is enabled
        if self.newsletter_generator and self.newsletter_generator.enabled:
            # Daily newsletter - generate at 6 AM every day
            self.scheduler.add_job(
                self.generate_newsletter,
                trigger=CronTrigger(hour=6, minute=0),
                id="newsletter_daily",
                name="Generate Daily Newsletter",
                kwargs={"period_type": "daily"},
                replace_existing=True,
            )
            logger.info("Scheduled daily newsletter generation (6:00 AM)")

            # Weekly newsletter - generate on Mondays at 7 AM
            self.scheduler.add_job(
                self.generate_newsletter,
                trigger=CronTrigger(day_of_week="mon", hour=7, minute=0),
                id="newsletter_weekly",
                name="Generate Weekly Newsletter",
                kwargs={"period_type": "weekly"},
                replace_existing=True,
            )
            logger.info("Scheduled weekly newsletter generation (Mondays 7:00 AM)")

            # Monthly newsletter - generate on the 1st at 8 AM
            self.scheduler.add_job(
                self.generate_newsletter,
                trigger=CronTrigger(day=1, hour=8, minute=0),
                id="newsletter_monthly",
                name="Generate Monthly Newsletter",
                kwargs={"period_type": "monthly"},
                replace_existing=True,
            )
            logger.info("Scheduled monthly newsletter generation (1st of month 8:00 AM)")

    async def generate_newsletter(self, period_type: str) -> None:
        """
        Generate a newsletter for the specified period.
        
        Args:
            period_type: One of 'daily', 'weekly', 'monthly', 'quarterly', 'annual'
        """
        if not self.newsletter_generator or not self.newsletter_generator.enabled:
            logger.warning("Newsletter generation disabled")
            return

        try:
            ptype = PeriodType(period_type)
            period_start, period_end = get_period_dates(ptype)
            
            logger.info(f"Generating {period_type} newsletter for {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}")
            
            async with self.db_pool.acquire() as conn:
                # Check if newsletter already exists for this period
                existing = await conn.fetchrow("""
                    SELECT id FROM newsletters
                    WHERE period_type = $1 AND period_start = $2
                """, period_type, period_start)
                
                if existing:
                    logger.info(f"Newsletter already exists for {period_type} {period_start.strftime('%Y-%m-%d')}")
                    return
                
                # Get events for this period with their AI summaries
                events = await conn.fetch("""
                    SELECT 
                        e.id, e.title, e.description, e.start_time, e.end_time,
                        e.location, e.category, e.ai_summary,
                        COALESCE(
                            json_agg(
                                json_build_object(
                                    'id', d.id,
                                    'title', d.title,
                                    'document_type', d.document_type
                                )
                            ) FILTER (WHERE d.id IS NOT NULL),
                            '[]'
                        ) as documents
                    FROM events e
                    LEFT JOIN event_documents ed ON e.id = ed.event_id
                    LEFT JOIN documents d ON ed.document_id = d.id
                    WHERE e.start_time BETWEEN $1 AND $2
                    GROUP BY e.id
                    ORDER BY e.start_time ASC
                """, period_start, period_end)
                
                # Get city name from first config
                city_name = "Community"
                if self._configs:
                    city_name = self._configs[0].city_profile.name
                
                # Convert to list of dicts
                events_list = [dict(e) for e in events]
                
                # Generate newsletter title
                title = generate_newsletter_title(ptype, period_start, city_name)
                
                # Create newsletter record first (pending)
                newsletter_id = await conn.fetchval("""
                    INSERT INTO newsletters (
                        city_id, title, period_type, period_start, period_end,
                        status, event_count, generation_started_at
                    ) VALUES ($1, $2, $3, $4, $5, 'generating', $6, NOW())
                    RETURNING id
                """, city_name.lower().replace(' ', '_').replace(',', ''), title, 
                    period_type, period_start, period_end, len(events_list))
                
                try:
                    # Generate newsletter content
                    summary_text = await self.newsletter_generator.generate_newsletter(
                        period_type=ptype,
                        period_start=period_start,
                        period_end=period_end,
                        events=events_list,
                        city_name=city_name,
                    )
                    
                    # Count documents
                    doc_count = sum(len(e.get("documents", [])) for e in events_list)
                    
                    # Update newsletter record
                    await conn.execute("""
                        UPDATE newsletters SET
                            status = 'completed',
                            summary_text = $1,
                            event_count = $2,
                            document_count = $3,
                            generation_completed_at = NOW()
                        WHERE id = $4
                    """, summary_text, len(events_list), doc_count, newsletter_id)
                    
                    logger.info(f"Generated {period_type} newsletter: {title} ({len(events_list)} events)")
                    
                except Exception as e:
                    # Mark as failed
                    await conn.execute("""
                        UPDATE newsletters SET
                            status = 'failed',
                            error_message = $1,
                            generation_completed_at = NOW()
                        WHERE id = $2
                    """, str(e), newsletter_id)
                    raise
                
        except Exception as e:
            logger.error(f"Error generating {period_type} newsletter: {e}")

    async def process_manual_triggers(self) -> None:
        """
        Check for and process manually triggered scrapes from the admin UI.
        
        Looks for sources where trigger_requested_at > last_fetched_at.
        """
        try:
            async with self.db_pool.acquire() as conn:
                # Find sources that need to be triggered
                triggered = await conn.fetch("""
                    SELECT id, name, driver_type, config, city_id
                    FROM sources
                    WHERE is_enabled = true
                      AND trigger_requested_at IS NOT NULL
                      AND (last_fetched_at IS NULL OR trigger_requested_at > last_fetched_at)
                """)
                
                if not triggered:
                    return
                
                logger.info(f"Manual trigger: Found {len(triggered)} sources to scrape")
                
                for row in triggered:
                    source_name = row['name']
                    city_id = row['city_id']
                    
                    # Find matching config
                    matching_config = None
                    matching_source = None
                    
                    for config in self._configs:
                        # Normalize city name for comparison
                        config_city_id = config.city_profile.name.lower().replace(' ', '_').replace(',', '')
                        db_city_id = city_id.lower().replace(' ', '_').replace(',', '')
                        
                        if config_city_id == db_city_id or db_city_id.startswith(config_city_id.split('_')[0]):
                            for source in config.sources:
                                if source.name == source_name:
                                    matching_config = config
                                    matching_source = source
                                    break
                        if matching_config:
                            break
                    
                    if matching_config and matching_source:
                        logger.info(f"Manual trigger: Running scrape for {source_name}")
                        try:
                            await self.scrape_source(matching_config, matching_source, skip_queue_check=True)
                        except Exception as e:
                            logger.error(f"Manual trigger: Error scraping {source_name}: {e}")
                    else:
                        logger.warning(f"Manual trigger: Could not find config for {source_name} (city: {city_id})")
                        # Clear the trigger anyway to avoid repeated attempts
                        await conn.execute(
                            "UPDATE sources SET trigger_requested_at = NULL WHERE id = $1",
                            row['id']
                        )
                        
        except Exception as e:
            logger.error(f"Manual trigger check error: {e}")

    async def process_ai_analysis_queue(self) -> None:
        """
        Process documents and events that need AI analysis.
        
        Processing order (strict priority):
        Phase 1: Date-based linking (NO AI, NO SPEED LIMIT)
           - Links docs with meeting_date to events by exact date match
           - Runs until all date-linkable docs are processed
        Phase 2: AI-assisted linking (uses batch_size)
           - Links docs that have summaries but couldn't be date-matched
        Phase 3: Generate document summaries (uses batch_size)
           - Only runs after Phase 1 & 2 are clear
        Phase 4: Generate event summaries (uses batch_size)
           - Only runs after Phase 3 is clear
        """
        batch_size = self.settings.ai_queue_batch_size
        logger.info("AI analysis queue: Starting processing run...")
        
        if not self.doc_summarizer or not self.doc_summarizer.enabled:
            logger.debug("AI analysis queue: Summarizer not enabled, skipping")
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                # Phase 1: Date-based linking (NO SPEED LIMIT)
                # Process ALL date-linkable documents in one go
                date_linked = await self._process_date_based_linking(conn)
                
                # Phase 2: AI-assisted linking (for docs with summaries)
                # Only if Phase 1 is clear
                pending_date_linking = await self._get_date_linkable_count(conn)
                if pending_date_linking > 0:
                    logger.info(f"AI analysis queue: {pending_date_linking} docs still date-linkable, skipping AI phases")
                    return
                
                ai_linked = await self._process_ai_linking(conn, batch_size)
                
                # Phase 3: Generate document summaries
                # Only if Phase 1 & 2 are clear
                pending_ai_linking = await self._get_ai_linkable_count(conn)
                if pending_ai_linking > 0:
                    logger.info(f"AI analysis queue: {pending_ai_linking} docs pending AI linking, skipping summaries")
                    return
                
                await self._process_document_summaries(conn, batch_size)
                
                # Phase 4: Generate event summaries
                # Only if Phase 3 is clear (no docs within age limit needing summaries)
                max_age_days = int(os.getenv("AI_SUMMARY_MAX_AGE_DAYS", "365"))
                pending_summaries = await conn.fetchval("""
                    SELECT COUNT(*) FROM documents d
                    LEFT JOIN event_documents ed ON d.id = ed.document_id
                    LEFT JOIN events e ON ed.event_id = e.id
                    WHERE (d.ai_summary IS NULL OR d.ai_summary = '') 
                      AND d.local_path IS NOT NULL
                      AND d.document_type NOT IN ('ordinance', 'resolution')
                      AND COALESCE(d.meeting_date, e.start_time) >= NOW() - INTERVAL '1 day' * $1
                """, max_age_days)
                if pending_summaries > 0:
                    logger.info(f"AI analysis queue: {pending_summaries} docs need summaries (within {max_age_days} days), skipping event summaries")
                    return
                
                await self._process_event_summaries(conn, batch_size)
                
            logger.info("AI analysis queue: Processing run complete")
                        
        except Exception as e:
            logger.error(f"AI analysis queue error: {e}")

    async def _process_document_summaries(self, conn, batch_size: int) -> None:
        """Generate AI summaries for documents that don't have them.
        
        Prioritizes documents by meeting_date descending (newest first):
        - Future meetings processed first (upcoming events)
        - Then most recent past meetings
        - Works backwards in time from there
        
        This ensures upcoming meetings are always prioritized, and new documents
        are processed based on their date regardless of when they were added.
        
        Respects ai_summary_max_age_days setting to skip old documents.
        """
        # Build age filter if configured - only summarize documents within range
        max_age_days = self.settings.ai_summary_max_age_days
        age_filter = ""
        if max_age_days > 0:
            # Process documents within age limit (past or future)
            # Documents without meeting_date are processed (they're likely recent)
            age_filter = f"""AND (
                meeting_date >= NOW() - INTERVAL '{max_age_days} days'
                OR meeting_date IS NULL
            )"""
        
        docs = await conn.fetch(f"""
            SELECT id, title, document_type, content_markdown, local_path, source_url, linking_status, meeting_date
            FROM documents
            WHERE (ai_summary IS NULL OR ai_summary = '')
              AND local_path IS NOT NULL
              {age_filter}
            ORDER BY 
                -- Primary: Newest dates first (highest epoch timestamp)
                -- Documents with NULL meeting_date sorted to end
                meeting_date DESC NULLS LAST,
                -- Secondary: Prioritize docs that need summary for linking
                CASE WHEN linking_status = 'needs_summary' THEN 0 ELSE 1 END,
                -- Tertiary: Local files over remote content
                CASE 
                    WHEN local_path IS NOT NULL THEN 0 
                    WHEN document_type = 'video' AND source_url LIKE '%youtu%' THEN 1
                    ELSE 2 
                END,
                -- Finally: newest created first for docs without dates
                created_at DESC
            LIMIT $1
        """, batch_size)
        
        if not docs:
            if max_age_days > 0:
                logger.debug(f"AI analysis queue: No documents pending summaries (within {max_age_days} days)")
            else:
                logger.debug("AI analysis queue: No documents pending summaries")
            return
        
        logger.info(f"AI analysis queue: Processing {len(docs)} document summaries")
        
        for doc in docs:
            try:
                # Determine if this is a YouTube video
                video_url = None
                if doc["document_type"] == "video" and doc["source_url"]:
                    url = doc["source_url"]
                    if "youtu.be" in url or "youtube.com" in url:
                        video_url = url
                
                summary = await self.doc_summarizer.generate_summary(
                    title=doc["title"],
                    document_type=doc["document_type"],
                    content_text=doc["content_markdown"],
                    local_path=doc["local_path"],
                    video_url=video_url,
                )
                
                if summary:
                    await self.db_pool.update_document_ai_summary(
                        conn,
                        doc["id"],
                        ai_summary=summary,
                    )
                    logger.info(f"AI summary generated for '{doc['title']}'")
                    
                    # Extract legislation mentions from this document
                    # (only for meeting documents, not videos)
                    if doc["document_type"] != "video":
                        await self._extract_and_link_legislation(
                            conn,
                            doc["id"],
                            doc["title"],
                            doc["document_type"],
                            doc["content_markdown"],
                            doc["local_path"]
                        )
                    
                    # If doc was waiting for summary to link, reset linking status
                    if doc.get("linking_status") == "needs_summary":
                        await conn.execute("""
                            UPDATE documents SET linking_status = 'pending' WHERE id = $1
                        """, doc["id"])
                        logger.info(f"AI summary generated for '{doc['title']}' - now ready for linking")
                else:
                    # Mark as processed (empty summary) to avoid reprocessing
                    await conn.execute("""
                        UPDATE documents SET ai_summary = '' WHERE id = $1
                    """, doc["id"])
                    logger.debug(f"AI summary skipped for '{doc['title']}' (no content)")
                    
            except Exception as e:
                logger.warning(f"AI analysis failed for '{doc['title']}': {e}")
                # Don't mark as processed - will retry later    async def _get_pending_linking_count(self, conn) -> int:
        """Get count of documents that are ready to be linked but haven't been yet.
        
        Linkable documents are:
        1. Videos - can be linked by title/date match
        2. Documents with meeting_date - can be linked by exact date match
        3. Documents with AI summary - can use AI to find best match
        """
        result = await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status = 'pending_retry')
              AND (
                -- Videos can always be linked by title/date
                d.document_type = 'video'
                -- Documents with meeting_date can be linked by exact date match
                OR d.meeting_date IS NOT NULL
                -- Documents with AI summary can use AI linking
                OR (d.ai_summary IS NOT NULL AND d.ai_summary != '')
              )
        """)
        return result or 0

    async def _get_ai_queue_status(self, conn) -> dict:
        """
        Get the current status of the AI processing queue.
        
        Returns dict with:
        - pending_linking: docs ready to be linked (videos, has meeting_date, or has summary)
        - pending_summaries: docs that need summaries before they can be linked
        - pending_retry: docs that failed linking and are waiting for retry
        - blocked: docs that can't be processed (no events to link to, etc.)
        """
        # Docs that are ready to link:
        # - Videos (can link by title/date)
        # - Docs with meeting_date (can link by exact date)
        # - Docs with AI summary (can use AI linking)
        pending_linking = await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status = 'pending')
              AND (
                d.document_type = 'video'
                OR d.meeting_date IS NOT NULL
                OR (d.ai_summary IS NOT NULL AND d.ai_summary != '')
              )
        """) or 0
        
        # Docs waiting for retry (couldn't link before)
        pending_retry = await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND d.linking_status = 'pending_retry'
              AND (d.linking_retry_after IS NULL OR d.linking_retry_after <= NOW())
              AND (
                d.document_type = 'video'
                OR d.meeting_date IS NOT NULL
                OR (d.ai_summary IS NOT NULL AND d.ai_summary != '')
              )
        """) or 0
        
        # Docs that need summaries before they can be linked
        # These are non-video docs without meeting_date AND without summary
        # They have local_path (downloaded) so they CAN be summarized
        pending_summaries = await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND d.document_type != 'video'
              AND d.meeting_date IS NULL
              AND (d.ai_summary IS NULL OR d.ai_summary = '')
              AND d.local_path IS NOT NULL
        """) or 0
        
        # Blocked docs - can't process (no events nearby, retries exhausted, etc.)
        blocked = await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND d.linking_status = 'blocked'
        """) or 0
        
        return {
            'pending_linking': pending_linking,
            'pending_retry': pending_retry,
            'pending_summaries': pending_summaries,
            'blocked': blocked,
            'total_actionable': pending_linking + pending_retry + pending_summaries,
        }

    async def is_ai_queue_busy(self) -> bool:
        """
        Check if the AI queue has actionable work pending.
        
        Used to pause scraping/backfill when AI processing is backed up.
        Returns False if queue is empty or only has blocked items.
        """
        if not self.db_pool:
            return False
            
        async with self.db_pool.acquire() as conn:
            status = await self._get_ai_queue_status(conn)
            is_busy = status['total_actionable'] > 0
            
            if is_busy:
                logger.debug(
                    f"AI queue busy: {status['pending_linking']} linking, "
                    f"{status['pending_retry']} retry, {status['pending_summaries']} summaries, "
                    f"{status['blocked']} blocked"
                )
            
            return is_busy

    async def _get_date_linkable_count(self, conn) -> int:
        """Count documents that can be linked by date (no AI needed)."""
        return await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'pending_retry'))
              AND (d.linking_retry_after IS NULL OR d.linking_retry_after <= NOW())
              AND d.meeting_date IS NOT NULL
              AND d.document_type NOT IN ('ordinance', 'resolution')
        """) or 0

    async def _get_ai_linkable_count(self, conn) -> int:
        """Count documents that need AI to link (have summary but no date match)."""
        return await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'needs_summary'))
              AND d.meeting_date IS NULL
              AND d.ai_summary IS NOT NULL AND d.ai_summary != ''
              AND d.document_type NOT IN ('ordinance', 'resolution')
        """) or 0

    async def _process_date_based_linking(self, conn) -> int:
        """
        Phase 1: Link documents by date match (NO AI, NO SPEED LIMIT).
        
        Processes ALL documents that have meeting_date and can be linked
        by exact date match. This is fast and doesn't use AI.
        """
        # First, mark any ordinances/resolutions as not needing linking (standalone legislation)
        standalone_updated = await conn.execute("""
            UPDATE documents 
            SET linking_status = 'not_applicable'
            WHERE document_type IN ('ordinance', 'resolution')
              AND (linking_status IS NULL OR linking_status IN ('pending', 'pending_retry'))
        """)
        if standalone_updated and 'UPDATE' in standalone_updated:
            count = int(standalone_updated.split()[1]) if len(standalone_updated.split()) > 1 else 0
            if count > 0:
                logger.info(f"AI analysis queue: Marked {count} ordinances/resolutions as standalone (not_applicable)")
        
        # Get ALL date-linkable documents (no limit) - exclude standalone legislation
        docs = await conn.fetch("""
            SELECT d.id, d.title, d.document_type, d.meeting_date, d.source_id,
                   d.linking_status, d.linking_attempts
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'pending_retry'))
              AND (d.linking_retry_after IS NULL OR d.linking_retry_after <= NOW())
              AND d.meeting_date IS NOT NULL
              AND d.document_type NOT IN ('ordinance', 'resolution')
            ORDER BY d.meeting_date DESC, d.created_at DESC
        """)
        
        if not docs:
            logger.debug("AI analysis queue: No documents pending date-based linking")
            return 0
        
        logger.info(f"AI analysis queue: Phase 1 - Date-linking {len(docs)} documents")
        linked_count = 0
        
        for doc in docs:
            try:
                attempts = (doc.get("linking_attempts") or 0) + 1
                meeting_date = doc["meeting_date"]
                doc_date = meeting_date.date() if hasattr(meeting_date, 'date') else meeting_date
                
                # Find events on the exact date
                # For videos, search across ALL sources in the same city (videos come from YouTube, not agenda center)
                if doc["document_type"] == "video":
                    events = await conn.fetch("""
                        SELECT DISTINCT e.id, e.title, e.start_time, e.category
                        FROM events e
                        JOIN event_sources es ON e.id = es.event_id
                        JOIN sources s ON es.source_id = s.id
                        WHERE s.city_id = (SELECT city_id FROM sources WHERE id = $1)
                          AND DATE(e.start_time) = $2
                        ORDER BY e.start_time DESC
                    """, doc["source_id"], doc_date)
                else:
                    events = await conn.fetch("""
                        SELECT e.id, e.title, e.start_time, e.category
                        FROM events e
                        JOIN event_sources es ON e.id = es.event_id
                        WHERE es.source_id = $1
                          AND DATE(e.start_time) = $2
                        ORDER BY e.start_time DESC
                    """, doc["source_id"], doc_date)
                
                if not events:
                    # No events on this date - create one if we have agenda/minutes/video
                    if doc["document_type"] in ("agenda", "minutes", "video"):
                        event_id = await self._create_event_from_document(conn, doc)
                        if event_id:
                            await self.db_pool.link_document_to_event(conn, doc["id"], event_id)
                            await conn.execute("""
                                UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
                            """, doc["id"], attempts)
                            logger.info(f"Created event from '{doc['title']}' and linked")
                            linked_count += 1
                            continue
                    
                    # No events and can't create one - mark for retry
                    await conn.execute("""
                        UPDATE documents 
                        SET linking_status = 'pending_retry', 
                            linking_attempts = $2,
                            linking_retry_after = NOW() + INTERVAL '1 hour'
                        WHERE id = $1
                    """, doc["id"], attempts)
                    logger.debug(f"No events on {doc_date} for '{doc['title']}' - retry later")
                    continue
                
                # Try to find best match
                exact_match = None
                doc_title_lower = doc["title"].lower()
                
                if len(events) == 1:
                    exact_match = events[0]
                else:
                    # Multiple events - match by title/category
                    best_match, best_score = None, 0
                    meeting_types = [
                        "city council", "council", "planning commission", "planning",
                        "zoning", "board of zoning", "finance", "finance committee",
                        "parks", "recreation", "school board", "board of education",
                        "township", "trustees",
                    ]
                    
                    for e in events:
                        event_title_lower = e["title"].lower()
                        event_category_lower = (e["category"] or "").lower()
                        score = 0
                        
                        for meeting_type in meeting_types:
                            if meeting_type in doc_title_lower:
                                if meeting_type in event_title_lower or meeting_type in event_category_lower:
                                    score += 10
                                else:
                                    score -= 5
                        
                        event_words = set(event_title_lower.split())
                        doc_words = set(doc_title_lower.split())
                        common = event_words & doc_words - {"meeting", "agenda", "minutes", "the", "of", "and", "for"}
                        score += len(common) * 2
                        
                        if score > best_score:
                            best_score, best_match = score, e
                    
                    if best_match and best_score > 0:
                        exact_match = best_match
                
                if exact_match:
                    await self.db_pool.link_document_to_event(conn, doc["id"], exact_match["id"])
                    await conn.execute("""
                        UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
                    """, doc["id"], attempts)
                    logger.info(f"Date-linked '{doc['title']}' → '{exact_match['title']}'")
                    linked_count += 1
                else:
                    # Multiple events, couldn't determine which - needs AI
                    await conn.execute("""
                        UPDATE documents SET linking_status = 'needs_summary' WHERE id = $1
                    """, doc["id"])
                    logger.debug(f"'{doc['title']}' has multiple events on {doc_date} - needs AI")
                    
            except Exception as e:
                logger.warning(f"Date-linking failed for '{doc['title']}': {e}")
        
        logger.info(f"AI analysis queue: Phase 1 complete - {linked_count} documents linked by date")
        return linked_count

    async def _create_event_from_document(self, conn, doc: dict) -> Optional[int]:
        """
        Create an event from an agenda, minutes, or video document.
        
        Extracts meeting info from the document title and creates a new event.
        Returns the event ID if successful, None otherwise.
        """
        title = doc["title"]
        meeting_date = doc["meeting_date"]
        source_id = doc["source_id"]
        
        # Parse event title from document title
        # Examples: "Regular Council Meeting - Agenda", "Planning Commission - Minutes"
        #           "Twinsburg Board of Education Meeting - May 21, 2025 - Video"
        event_title = title
        
        # Remove common suffixes (including video)
        for suffix in [" - Agenda", " - Minutes", " - Video", " Agenda", " Minutes", " Video", 
                       " - agenda", " - minutes", " - video"]:
            if event_title.endswith(suffix):
                event_title = event_title[:-len(suffix)]
                break
        
        # Remove date patterns that might be in the title
        import re
        # "- May 21, 2025" or "- 5/21/2025" or "1/12/2025"
        event_title = re.sub(r'\s*-?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$', '', event_title)
        event_title = re.sub(r'\s*-?\s*\w+ \d{1,2},? \d{4}\s*$', '', event_title)
        # Also handle "May 21, 2025" without dash
        event_title = re.sub(r'\s*-?\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\s*$', '', event_title, flags=re.IGNORECASE)
        
        event_title = event_title.strip()
        # Remove trailing dash if present
        event_title = event_title.rstrip(' -').strip()
        
        if not event_title:
            event_title = "Meeting"
        
        # Determine category from title
        category = None
        title_lower = event_title.lower()
        if "council" in title_lower:
            category = "city_council"
        elif "planning" in title_lower:
            category = "planning_commission"
        elif "zoning" in title_lower:
            category = "zoning_board"
        elif "school" in title_lower or "education" in title_lower or "board of education" in title_lower:
            category = "school_board"
        elif "finance" in title_lower:
            category = "finance_committee"
        elif "parks" in title_lower or "recreation" in title_lower:
            category = "parks_recreation"
        elif "committee" in title_lower:
            category = "committee"
        else:
            category = "meeting"
        
        # Use the meeting date as-is (don't assume a time)
        from datetime import datetime
        if hasattr(meeting_date, 'date'):
            start_time = meeting_date
        else:
            # It's a date object, convert to datetime at midnight
            start_time = datetime.combine(meeting_date, datetime.min.time())
        
        try:
            # Create the event
            row = await conn.fetchrow("""
                INSERT INTO events (title, start_time, category, created_at, updated_at)
                VALUES ($1, $2, $3, NOW(), NOW())
                RETURNING id
            """, event_title, start_time, category)
            
            event_id = row["id"]
            
            # Link the event to the source
            await conn.execute("""
                INSERT INTO event_sources (event_id, source_id, first_seen_at, last_seen_at)
                VALUES ($1, $2, NOW(), NOW())
                ON CONFLICT (event_id, source_id) DO NOTHING
            """, event_id, source_id)
            
            logger.info(f"Created event '{event_title}' on {start_time.date()} from document")
            return event_id
            
        except Exception as e:
            logger.warning(f"Failed to create event from document '{title}': {e}")
            return None

    async def _process_ai_linking(self, conn, batch_size: int) -> int:
        """
        Phase 2: Link documents using AI (for docs with summaries but no date match).
        """
        if not self.ai_processor or not self.ai_processor.enabled:
            return 0
        
        docs = await conn.fetch("""
            SELECT d.id, d.title, d.document_type, d.ai_summary, d.meeting_date, d.source_id,
                   d.linking_status, d.linking_attempts
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'needs_summary'))
              AND d.ai_summary IS NOT NULL AND d.ai_summary != ''
            ORDER BY d.created_at DESC
            LIMIT $1
        """, batch_size)
        
        if not docs:
            logger.debug("AI analysis queue: No documents pending AI linking")
            return 0
        
        logger.info(f"AI analysis queue: Phase 2 - AI-linking {len(docs)} documents")
        linked_count = 0
        
        for doc in docs:
            try:
                attempts = (doc.get("linking_attempts") or 0) + 1
                meeting_date = doc["meeting_date"] or datetime.now()
                
                # Get nearby events
                events = await conn.fetch("""
                    SELECT e.id, e.title, e.start_time, e.category
                    FROM events e
                    JOIN event_sources es ON e.id = es.event_id
                    WHERE es.source_id = $1
                      AND e.start_time BETWEEN ($2::timestamp - INTERVAL '30 days') AND ($2::timestamp + INTERVAL '30 days')
                    ORDER BY e.start_time DESC
                    LIMIT 20
                """, doc["source_id"], meeting_date)
                
                if not events:
                    await conn.execute("""
                        UPDATE documents 
                        SET linking_status = 'pending_retry', linking_attempts = $2,
                            linking_retry_after = NOW() + INTERVAL '1 hour'
                        WHERE id = $1
                    """, doc["id"], attempts)
                    logger.debug(f"No nearby events for AI linking '{doc['title']}'")
                    continue
                
                events_context = [
                    {"id": e["id"], "title": e["title"], 
                     "date": e["start_time"].isoformat() if e["start_time"] else None,
                     "type": e["category"]}
                    for e in events
                ]
                
                matches = await self.ai_processor.find_related_events(
                    document_title=doc["title"],
                    document_type=doc["document_type"],
                    document_content=doc["ai_summary"],  # Use summary as content for AI linking
                    events=events_context,
                )
                
                if matches:
                    for match in matches:
                        await self.db_pool.link_document_to_event(
                            conn, doc["id"], match["event_id"],
                            confidence=match.get("confidence", 0.5),
                        )
                    await conn.execute("""
                        UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
                    """, doc["id"], attempts)
                    logger.info(f"AI-linked '{doc['title']}' to {len(matches)} event(s)")
                    linked_count += 1
                else:
                    if attempts >= 3:
                        await conn.execute("""
                            UPDATE documents SET linking_status = 'blocked', linking_attempts = $2 WHERE id = $1
                        """, doc["id"], attempts)
                        logger.info(f"Blocked '{doc['title']}' after {attempts} attempts")
                    else:
                        await conn.execute("""
                            UPDATE documents 
                            SET linking_status = 'pending_retry', linking_attempts = $2,
                                linking_retry_after = NOW() + INTERVAL '1 hour'
                            WHERE id = $1
                        """, doc["id"], attempts)
                        
            except Exception as e:
                logger.warning(f"AI linking failed for '{doc['title']}': {e}")
        
        logger.info(f"AI analysis queue: Phase 2 complete - {linked_count} documents AI-linked")
        return linked_count

    async def _process_document_linking(self, conn, batch_size: int) -> int:
        """Link documents to events. Returns count of docs processed.
        
        Processes documents in priority order:
        1. Videos - can link by title/date match (no summary needed)
        2. Documents with meeting_date - can link by exact date match (no summary needed)
        3. Documents with AI summary - can use AI to find best event match
        """
        if not self.ai_processor or not self.ai_processor.enabled:
            return 0
        
        # Find documents ready for linking:
        # - Videos (can always link by title/date)
        # - Docs with meeting_date (can link by exact date)
        # - Docs with AI summary (can use AI linking)
        docs = await conn.fetch("""
            SELECT d.id, d.title, d.document_type, d.ai_summary, d.meeting_date, d.source_id,
                   d.linking_status, d.linking_attempts, d.local_path
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'pending_retry'))
              AND (d.linking_retry_after IS NULL OR d.linking_retry_after <= NOW())
              AND (
                -- Videos can always be linked
                d.document_type = 'video'
                -- Docs with meeting_date can be linked by date
                OR d.meeting_date IS NOT NULL
                -- Docs with AI summary can use AI linking
                OR (d.ai_summary IS NOT NULL AND d.ai_summary != '')
              )
            ORDER BY 
                -- Priority: 1=video, 2=has meeting_date, 3=has summary only
                CASE 
                    WHEN d.document_type = 'video' THEN 1
                    WHEN d.meeting_date IS NOT NULL THEN 2
                    ELSE 3
                END,
                CASE WHEN d.linking_status IS NULL THEN 0 ELSE 1 END,  -- New docs first
                d.meeting_date DESC NULLS LAST, 
                d.created_at DESC
            LIMIT $1
        """, batch_size)
        
        if not docs:
            logger.debug("AI analysis queue: No documents pending linking")
            return 0
        
        logger.info(f"AI analysis queue: Linking {len(docs)} documents to events")
        linked_count = 0
        
        for doc in docs:
            try:
                # Track linking attempts
                attempts = (doc.get("linking_attempts") or 0) + 1
                
                # Get events near the document's meeting date
                meeting_date = doc["meeting_date"] or datetime.now()
                
                # For videos, search across ALL sources in the same city (since videos are from YouTube, not agenda center)
                # For other documents, search within the same source only
                if doc["document_type"] == "video":
                    # Get the city_id for this source, then find events from any source in that city
                    events = await conn.fetch("""
                        SELECT DISTINCT e.id, e.title, e.start_time, e.category
                        FROM events e
                        JOIN event_sources es ON e.id = es.event_id
                        JOIN sources s ON es.source_id = s.id
                        WHERE s.city_id = (SELECT city_id FROM sources WHERE id = $1)
                          AND e.start_time BETWEEN ($2::timestamp - INTERVAL '7 days') AND ($2::timestamp + INTERVAL '7 days')
                        ORDER BY e.start_time DESC
                        LIMIT 20
                    """, doc["source_id"], meeting_date)
                else:
                    # For non-video docs, search within the same source
                    events = await conn.fetch("""
                        SELECT e.id, e.title, e.start_time, e.category
                        FROM events e
                        JOIN event_sources es ON e.id = es.event_id
                        WHERE es.source_id = $1
                          AND e.start_time BETWEEN ($2::timestamp - INTERVAL '7 days') AND ($2::timestamp + INTERVAL '7 days')
                        ORDER BY e.start_time DESC
                        LIMIT 20
                    """, doc["source_id"], meeting_date)
                
                logger.info(f"Processing doc '{doc['title']}' (source={doc['source_id']}, date={meeting_date}): found {len(events)} nearby events")
                
                if not events:
                    # No events to link to - mark for retry later (maybe events will be scraped later)
                    # Set retry_after to 1 hour from now so we move on to other documents
                    await conn.execute("""
                        UPDATE documents 
                        SET linking_status = 'pending_retry', 
                            linking_attempts = $2,
                            linking_retry_after = NOW() + INTERVAL '1 hour'
                        WHERE id = $1
                    """, doc["id"], attempts)
                    logger.info(f"No nearby events for '{doc['title']}' - marked for retry in 1 hour")
                    continue
                
                # First try: exact date match with title/category matching
                # This handles cases where multiple meetings occur on the same day
                doc_title_lower = doc["title"].lower()
                doc_date = meeting_date.date() if hasattr(meeting_date, 'date') else meeting_date
                
                # Find all events on the exact date
                same_day_events = [
                    e for e in events 
                    if e["start_time"] and e["start_time"].date() == doc_date
                ]
                
                exact_match = None
                if len(same_day_events) == 1:
                    # Only one event on this day - use it
                    exact_match = same_day_events[0]
                    logger.debug(f"Single event on {doc_date}: '{exact_match['title']}'")
                elif len(same_day_events) > 1:
                    # Multiple events on same day - try to match by title/category
                    logger.debug(f"Multiple events on {doc_date}: {[e['title'] for e in same_day_events]}")
                    
                    # Extract key words from document title for matching
                    # Common patterns: "City Council Agenda", "Planning Commission Minutes"
                    best_match = None
                    best_score = 0
                    
                    for e in same_day_events:
                        event_title_lower = e["title"].lower()
                        event_category_lower = (e["category"] or "").lower()
                        
                        # Calculate a simple match score
                        score = 0
                        
                        # Check for common meeting type keywords
                        meeting_types = [
                            "city council", "council", 
                            "planning commission", "planning",
                            "zoning", "board of zoning",
                            "finance", "finance committee",
                            "parks", "recreation",
                            "school board", "board of education",
                            "township", "trustees",
                        ]
                        
                        for meeting_type in meeting_types:
                            if meeting_type in doc_title_lower:
                                if meeting_type in event_title_lower or meeting_type in event_category_lower:
                                    score += 10  # Strong match
                                else:
                                    score -= 5  # Doc mentions a type but event doesn't match
                        
                        # Also check if event title words appear in doc title
                        event_words = set(event_title_lower.split())
                        doc_words = set(doc_title_lower.split())
                        common_words = event_words & doc_words - {"meeting", "agenda", "minutes", "the", "of", "and", "for"}
                        score += len(common_words) * 2
                        
                        if score > best_score:
                            best_score = score
                            best_match = e
                    
                    if best_match and best_score > 0:
                        exact_match = best_match
                        logger.debug(f"Best title match (score={best_score}): '{exact_match['title']}'")
                    else:
                        # Can't determine which event - fall through to AI matching
                        logger.debug(f"No clear title match, will use AI")
                
                if exact_match:
                    # Direct link without AI - exact date match is highly reliable
                    await self.db_pool.link_document_to_event(
                        conn,
                        doc["id"],
                        exact_match["id"],
                    )
                    # Mark as successfully linked
                    await conn.execute("""
                        UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
                    """, doc["id"], attempts)
                    logger.info(f"Linked '{doc['title']}' to event '{exact_match['title']}' (exact date match)")
                    linked_count += 1
                    continue
                
                # No exact date match - need AI summary to proceed
                # If no summary, mark as needing summary and skip
                if not doc["ai_summary"]:
                    if doc["local_path"]:
                        # Has file, can be summarized - mark for summary generation
                        await conn.execute("""
                            UPDATE documents 
                            SET linking_status = 'needs_summary'
                            WHERE id = $1
                        """, doc["id"])
                        logger.info(f"'{doc['title']}' needs AI summary before linking (no exact date match)")
                    else:
                        # No file, no summary, no exact match - block it
                        await conn.execute("""
                            UPDATE documents 
                            SET linking_status = 'blocked', linking_attempts = $2
                            WHERE id = $1
                        """, doc["id"], attempts)
                        logger.info(f"Blocked '{doc['title']}' - no file, no summary, no exact date match")
                    continue
                
                # Second try: use AI to find best match from nearby events
                events_context = [
                    {
                        "id": e["id"],
                        "title": e["title"],
                        "date": e["start_time"].isoformat() if e["start_time"] else None,
                        "type": e["category"],
                    }
                    for e in events
                ]
                
                matches = await self.ai_processor.find_related_events(
                    document_title=doc["title"],
                    document_type=doc["document_type"],
                    document_content=doc["ai_summary"],  # Use summary as content for AI linking
                    events=events_context,
                )
                
                if matches:
                    for match in matches:
                        await self.db_pool.link_document_to_event(
                            conn,
                            doc["id"],
                            match["event_id"],
                            confidence=match.get("confidence", 0.5),
                        )
                        logger.info(f"Linked '{doc['title']}' to event {match['event_id']}")
                    # Mark as successfully linked
                    await conn.execute("""
                        UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
                    """, doc["id"], attempts)
                    linked_count += 1
                else:
                    # No AI matches - mark for retry or block after too many attempts
                    if attempts >= 3:
                        # Block after 3 attempts - likely no matching event exists
                        await conn.execute("""
                            UPDATE documents 
                            SET linking_status = 'blocked', linking_attempts = $2 
                            WHERE id = $1
                        """, doc["id"], attempts)
                        logger.info(f"Blocked '{doc['title']}' - no matching events after {attempts} attempts")
                    else:
                        # Schedule for retry in 1 hour
                        await conn.execute("""
                            UPDATE documents 
                            SET linking_status = 'pending_retry', 
                                linking_attempts = $2,
                                linking_retry_after = NOW() + INTERVAL '1 hour'
                            WHERE id = $1
                        """, doc["id"], attempts)
                        logger.info(f"Queued '{doc['title']}' for retry (attempt {attempts}/3)")
                    
            except Exception as e:
                logger.warning(f"AI linking failed for '{doc['title']}': {e}")
                # Mark for retry on error
                await conn.execute("""
                    UPDATE documents 
                    SET linking_status = 'pending_retry',
                        linking_retry_after = NOW() + INTERVAL '5 minutes'
                    WHERE id = $1
                """, doc["id"])
        
        return linked_count

    async def _extract_and_link_legislation(
        self,
        conn,
        document_id: int,
        doc_title: str,
        doc_type: str,
        content_markdown: Optional[str],
        local_path: Optional[str]
    ) -> None:
        """
        Extract legislation mentions from a document and create links.
        
        This is called after a document summary is generated.
        Extracts structured legislation data and stores in legislation_mentions table.
        """
        if not self.doc_summarizer or not self.doc_summarizer.enabled:
            return
        
        try:
            # Extract legislation mentions from the document
            legislation_list = await self.doc_summarizer.extract_legislation(
                title=doc_title,
                document_type=doc_type,
                content_text=content_markdown,
                local_path=local_path,
            )
            
            if not legislation_list:
                logger.debug(f"No legislation found in '{doc_title}'")
                return
            
            logger.info(f"Extracted {len(legislation_list)} legislation mentions from '{doc_title}'")
            
            # Try to find linked event for this document
            event_id = await conn.fetchval("""
                SELECT event_id FROM event_documents WHERE document_id = $1 LIMIT 1
            """, document_id)
            
            # Store each legislation mention
            for legis in legislation_list:
                try:
                    # Extract fields with defaults, handling None values
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
                    
                    # Get document meeting date for linking
                    doc = await conn.fetchrow("""
                        SELECT meeting_date FROM documents WHERE id = $1
                    """, document_id)
                    
                    mentioned_date = doc["meeting_date"] if doc else None
                    
                    # Check if this mention already exists
                    existing = await conn.fetchrow("""
                        SELECT id FROM legislation_mentions
                        WHERE document_id = $1
                          AND legislation_number = $2
                          AND action_taken = $3
                    """, document_id, legis_number, action)
                    
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
                        """, document_id, event_id, legis_type, legis_number,
                            legis_title, action, vote_result, vote_details,
                            excerpt, mentioned_date)
                        logger.debug(f"Created legislation mention: {legis_type} {legis_number} ({action})")
                        
                except Exception as e:
                    logger.warning(f"Failed to store legislation mention: {e}")
                    continue
                    
        except Exception as e:
            logger.warning(f"Legislation extraction failed for '{doc_title}': {e}")

    async def _process_event_summaries(self, conn, batch_size: int) -> None:
        """Generate AI summaries for events that have linked documents.
        
        Prioritizes by start_time descending (newest/future events first).
        Respects ai_summary_max_age_days setting to skip old events.
        """
        # Build age filter if configured
        max_age_days = self.settings.ai_summary_max_age_days
        age_filter = ""
        if max_age_days > 0:
            age_filter = f"AND e.start_time >= NOW() - INTERVAL '{max_age_days} days'"
        
        # Find events that need summaries and have properly linked documents
        # Ordered by start_time DESC (newest/future events first)
        events = await conn.fetch(f"""
            SELECT DISTINCT e.id, e.title, e.start_time, e.category
            FROM events e
            JOIN event_documents ed ON e.id = ed.event_id
            JOIN documents d ON ed.document_id = d.id
            WHERE e.ai_summary IS NULL
              AND d.ai_summary IS NOT NULL
              AND d.ai_summary != ''
              AND ed.relationship NOT IN ('none', 'unlinked')
              {age_filter}
            ORDER BY e.start_time DESC NULLS LAST
            LIMIT $1
        """, batch_size)
        
        if not events:
            if max_age_days > 0:
                logger.debug(f"AI analysis queue: No events pending summaries (within {max_age_days} days)")
            else:
                logger.debug("AI analysis queue: No events pending summaries")
            return
        
        logger.info(f"AI analysis queue: Processing {len(events)} event summaries")
        
        for event in events:
            try:
                await self._generate_event_summary(conn, event["id"])
            except Exception as e:
                logger.warning(f"Event summary failed for '{event['title']}': {e}")

    async def scrape_source(
        self,
        config,
        source,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        skip_queue_check: bool = False,
    ) -> tuple[list, list]:
        """
        Execute a single scraping job.
        
        Args:
            config: City configuration
            source: Source configuration to scrape
            start_date: Optional start date for historical scraping
            end_date: Optional end date for historical scraping
            skip_queue_check: If True, skip AI queue busy check (for manual triggers)
            
        Returns:
            Tuple of (events, documents) for backfill tracking
        """
        # Check if AI queue has pending work - if so, skip scraping to let it catch up
        if not skip_queue_check and await self.is_ai_queue_busy():
            logger.info(f"Skipping scrape for {source.name} - AI queue has pending work")
            return [], []
        
        date_range = ""
        if start_date and end_date:
            date_range = f" ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})"
        logger.info(f"Starting scrape: {config.city_profile.name} / {source.name}{date_range}")
        
        events = []
        documents = []
        
        try:
            # Get the appropriate driver
            driver_class = get_driver(source.driver)
            
            # Create driver with optional date range for backfill
            driver_params = dict(source.params) if source.params else {}
            if start_date and end_date:
                # Override date range params for backfill
                driver_params["start_date"] = start_date
                driver_params["end_date"] = end_date
                driver_params["backfill_mode"] = True
            
            driver = driver_class(
                source_config=source,
                city_config=config,
                params_override=driver_params,
            )

            # Execute the scrape
            events, documents = await driver.fetch()

            # Store results
            if self.db_pool:
                async with self.db_pool.acquire() as conn:
                    await self._store_results(
                        conn=conn,
                        source=source,
                        events=events,
                        documents=documents,
                        city_name=config.city_profile.name,
                    )

            logger.info(
                f"Completed scrape: {source.name} - "
                f"{len(events)} events, {len(documents)} documents"
            )
            
            return events, documents

        except Exception as e:
            logger.error(f"Scrape failed: {source.name} - {e}")
            # Don't re-raise - we want to continue with other sources
            # TODO: Update source health status in database
            raise  # Re-raise for backfill error handling

    async def _ai_link_documents_to_events(
        self,
        conn,
        documents: list[tuple[int, Document]],
    ) -> None:
        """
        Use AI to intelligently link standalone documents to existing events.
        
        Acts as an AI secretary that reviews documents and finds matching events
        based on title similarity, content, and context.
        
        Args:
            conn: Database connection
            documents: List of (doc_id, Document) tuples to process
        """
        from datetime import datetime, timedelta
        
        # Get events for matching (past year + next 90 days)
        # We need a wide range to match historical documents with their events
        past_cutoff = datetime.now() - timedelta(days=365)
        future_cutoff = datetime.now() + timedelta(days=90)
        events = await conn.fetch("""
            SELECT id, title, start_time, description
            FROM events
            WHERE start_time >= $1
              AND start_time <= $2
            ORDER BY start_time
        """, past_cutoff, future_cutoff)
        
        if not events:
            logger.debug("No upcoming events to match documents against")
            return
        
        events_list = [
            {
                'id': e['id'],
                'title': e['title'],
                'start_time': e['start_time'].isoformat() if e['start_time'] else 'Unknown',
                'description': e['description']
            }
            for e in events
        ]
        
        for doc_id, document in documents:
            try:
                # Use meeting_date for linking (when the meeting occurred)
                # Fall back to published_at if meeting_date not available
                doc_date = None
                if hasattr(document, 'meeting_date') and document.meeting_date:
                    doc_date = document.meeting_date.strftime('%Y-%m-%d')
                elif hasattr(document, 'published_at') and document.published_at:
                    doc_date = document.published_at.strftime('%Y-%m-%d')
                
                # Get local path if downloaded (stored as file_path in Document model)
                local_path = None
                if hasattr(document, 'file_path') and document.file_path:
                    local_path = document.file_path
                
                # Get content - Document model uses content_markdown, not content
                doc_content = None
                if hasattr(document, 'content_markdown') and document.content_markdown:
                    doc_content = document.content_markdown
                
                # Get document type - handle both enum and string cases
                doc_type_str = None
                if hasattr(document, 'doc_type') and document.doc_type:
                    # DocumentType is (str, Enum), so it can be used as string directly
                    # But handle case where it might be a plain string
                    doc_type_str = str(document.doc_type.value) if hasattr(document.doc_type, 'value') else str(document.doc_type)
                
                # Use AI to find related events
                matches = await self.ai_processor.find_related_events(
                    document_title=document.title,
                    document_content=doc_content,
                    events=events_list,
                    document_date=doc_date,
                    document_type=doc_type_str,
                    local_path=local_path,
                )
                
                # Create the links
                for match in matches:
                    await conn.execute("""
                        INSERT INTO event_documents (event_id, document_id, relationship)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (event_id, document_id) DO NOTHING
                    """, match['event_id'], doc_id, match.get('relationship', 'attachment'))
                
                if matches:
                    logger.info(
                        f"AI linked document '{document.title}' to {len(matches)} events"
                    )
                    # Generate/update AI summaries for linked events
                    for match in matches:
                        await self._generate_event_summary(conn, match['event_id'])
                    
            except Exception as e:
                logger.warning(f"AI document linking failed for '{document.title}': {e}")

    async def _generate_event_summary(
        self,
        conn,
        event_id: int,
    ) -> None:
        """
        Generate or update the AI summary for an event.
        
        Called after documents are linked to ensure the summary reflects
        all available information.
        
        Args:
            conn: Database connection
            event_id: ID of the event to summarize
        """
        if not self.ai_processor or not self.ai_processor.enabled:
            return
            
        try:
            # Fetch event details
            event_row = await conn.fetchrow("""
                SELECT id, title, description, start_time, location, category
                FROM events
                WHERE id = $1
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
            
            # Fetch event sources
            source_rows = await conn.fetch("""
                SELECT s.name, es.raw_data
                FROM event_sources es
                JOIN sources s ON es.source_id = s.id
                WHERE es.event_id = $1
            """, event_id)
            
            sources = [
                {'name': r['name'], 'raw_data': r['raw_data']}
                for r in source_rows
            ]
            
            # Fetch associated documents (including AI summaries)
            doc_rows = await conn.fetch("""
                SELECT d.id, d.title, d.document_type, ed.relationship, 
                       d.content_text, d.local_path, d.ai_summary
                FROM event_documents ed
                JOIN documents d ON ed.document_id = d.id
                WHERE ed.event_id = $1
            """, event_id)
            
            documents = [
                {
                    'id': d['id'],
                    'title': d['title'],
                    'document_type': d['document_type'],
                    'relationship': d['relationship'],
                    'content_text': d['content_text'],
                    'local_path': d['local_path'],
                    'ai_summary': d['ai_summary'],
                }
                for d in doc_rows
            ]
            
            # Generate the summary
            summary = await self.ai_processor.generate_event_summary(
                event=event,
                sources=sources,
                documents=documents,
            )
            
            if summary:
                # Save to database
                await conn.execute("""
                    UPDATE events
                    SET ai_summary = $1, ai_summary_updated_at = NOW()
                    WHERE id = $2
                """, summary, event_id)
                
                logger.info(f"Generated AI summary for event '{event['title']}' (id={event_id})")
                
        except Exception as e:
            logger.warning(f"Failed to generate AI summary for event {event_id}: {e}")

    async def _download_and_update_document(
        self,
        conn,
        document: Document,
        doc_id: int,
        source_name: str,
    ) -> None:
        """
        Download a document and update the database.
        AI analysis is handled separately by the background AI processor.
        
        Args:
            conn: Database connection
            document: Document model
            doc_id: Database ID of the document
            source_name: Name of the source for organizing storage
        """
        if not self.document_downloader:
            return
        
        try:
            result = await self.document_downloader.download(
                url=document.original_url,
                source_name=source_name,
                document_id=doc_id,
                title=document.title,
            )
            
            if result and result.get("local_path"):
                local_path = result["local_path"]
                # Update document with local path
                await self.db_pool.update_document_local_path(
                    conn,
                    doc_id,
                    local_path=local_path,
                    file_size_bytes=result.get("file_size"),
                    mime_type=result.get("mime_type"),
                    file_hash=result.get("file_hash"),
                )
                logger.debug(f"Downloaded document '{document.title}' -> {local_path}")
            elif result is None:
                logger.debug(f"Skipped download for '{document.title}' (not downloadable)")
                
        except Exception as e:
            logger.warning(f"Error downloading '{document.title}': {e}")

    async def _store_results(self, conn, source, events: list, documents: list, city_name: str = "") -> None:
        """Store scraped results in database and download documents.
        
        AI analysis (summaries) is handled separately by the background
        AI analysis queue processor for better performance.
        
        Args:
            conn: Database connection
            source: Source configuration
            events: List of events to store
            documents: List of standalone documents to store
            city_name: Name of the city for AI context
        """
        if not events and not documents:
            return
            
        # Get or create the source record
        source_id = await self.db_pool.get_or_create_source(
            conn,
            name=source.name,
            driver=source.driver,
            config=source.params,
            is_enabled=source.enabled,
            schedule=source.schedule,
        )
        
        # Store events (with optional AI enrichment for deduplication)
        for event in events:
            try:
                # Optionally enrich with AI if configured (quick normalization only)
                if self.ai_processor and self.ai_processor.enabled:
                    event = await self._enrich_event_with_ai(event, city_name)
                
                # Pass AI processor for uncertain deduplication
                event_id = await self.db_pool.upsert_event(
                    conn, source_id, event, ai_processor=self.ai_processor
                )
                logger.debug(f"Stored event: {event.title} -> {event_id}")
                
                # Store documents attached to this event
                for document in event.documents:
                    try:
                        doc_id = await self.db_pool.upsert_document(
                            conn, source_id, document, event_id=event_id
                        )
                        logger.debug(f"Linked document '{document.title}' (id={doc_id}) to event {event_id}")
                        
                        # Download the document (AI analysis handled by queue)
                        await self._download_and_update_document(conn, document, doc_id, source.name)
                        
                    except Exception as e:
                        logger.error(f"Failed to store event document '{document.title}': {e}")
                        
            except Exception as e:
                logger.error(f"Failed to store event '{event.title}': {e}")
        
        # Store standalone documents (not linked to specific events)
        standalone_doc_ids = []
        for document in documents:
            try:
                doc_id = await self.db_pool.upsert_document(conn, source_id, document)
                standalone_doc_ids.append((doc_id, document))
                logger.debug(f"Stored standalone document: {document.title} -> {doc_id}")
                
                # Download the document
                await self._download_and_update_document(conn, document, doc_id, source.name)
                
            except Exception as e:
                logger.error(f"Failed to store document '{document.title}': {e}")
        
        # Note: AI document linking and summaries are handled by the background
        # AI analysis queue (process_ai_analysis_queue) for better performance
        
        # Update source health status
        await self.db_pool.update_source_health(conn, source_id, success=True)
        logger.info(f"Completed storing results for {source.name}: {len(events)} events, {len(documents)} documents")

    async def _initialize_all_sources(self, configs: list) -> None:
        """
        Initialize all sources from configs in the database.
        
        This ensures all sources appear in the admin UI immediately,
        even before they've been scraped.
        """
        async with self.db_pool.acquire() as conn:
            for config in configs:
                city_id = config.city_profile.name.lower().replace(" ", "_").replace(",", "")
                
                # Process both public and private sources
                all_sources = config.sources + config.private_sources
                
                for source in all_sources:
                    try:
                        source_id = await self.db_pool.get_or_create_source(
                            conn,
                            name=source.name,
                            driver=source.driver,
                            config=source.params,
                            city_id=city_id,
                            is_enabled=source.enabled,
                            schedule=source.schedule,
                        )
                        logger.debug(f"Initialized source '{source.name}' (id={source_id}, enabled={source.enabled})")
                    except Exception as e:
                        logger.warning(f"Failed to initialize source '{source.name}': {e}")
        
        logger.info(f"Initialized all sources from {len(configs)} config(s)")

    async def run(self) -> None:
        """Main run loop."""
        await self.initialize()

        # Load all city configurations
        configs_dir = Path(self.settings.configs_dir)
        configs = load_all_configs(configs_dir)
        self._configs = configs  # Store for backfill access
        logger.info(f"Loaded {len(configs)} city configuration(s)")

        # Initialize ALL sources in database (so they appear in admin immediately)
        await self._initialize_all_sources(configs)

        # Schedule all sources
        self.schedule_sources(configs)

        # Start the scheduler
        self.scheduler.start()
        logger.info("Scheduler started. Waiting for jobs...")

        # Run initial scrape for all sources (future + 1 week past)
        if self.settings.run_on_startup:
            logger.info("Running initial scrape for all sources (future + recent past)...")
            for config in configs:
                for source in config.sources:
                    if source.enabled:
                        try:
                            # Skip queue check for initial scrape
                            await self.scrape_source(config, source, skip_queue_check=True)
                            
                            # Initialize backfill queue for this source
                            if self.backfill_manager:
                                async with self.db_pool.acquire() as conn:
                                    source_id = await self.db_pool.get_or_create_source(
                                        conn,
                                        name=source.name,
                                        driver=source.driver,
                                        config=source.params,
                                        is_enabled=source.enabled,
                                        schedule=source.schedule,
                                    )
                                    await self.backfill_manager.initialize_queue_for_source(
                                        conn, source_id, source.name
                                    )
                        except Exception as e:
                            logger.error(f"Initial scrape failed for {source.name}: {e}")

        # Start background backfill processor
        if self.backfill_manager:
            logger.info("Starting historical backfill processor...")
            await self.backfill_manager.start_background_processor(
                scrape_callback=self.scrape_source,
                configs=configs,
                ai_queue_check_callback=self.is_ai_queue_busy,
            )
            
            # Log initial queue status
            async with self.db_pool.acquire() as conn:
                status = await self.backfill_manager.get_queue_status(conn)
                logger.info(
                    f"Backfill queue: {status['pending']} pending, "
                    f"{status['completed']} completed, {status['failed']} failed"
                )

        # Run AI analysis queue immediately after initial scrape
        if self.doc_summarizer and self.doc_summarizer.enabled:
            logger.info("Running initial AI analysis queue processing...")
            await self.process_ai_analysis_queue()  # Uses batch_size from settings

        # Wait for shutdown signal
        await self._shutdown_event.wait()


async def main() -> None:
    """Application entrypoint."""
    settings = Settings()
    worker = Worker(settings)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(worker.shutdown()),
        )

    try:
        await worker.run()
    except KeyboardInterrupt:
        pass
    finally:
        await worker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
