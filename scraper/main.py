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
        self.scheduler = AsyncIOScheduler()
        self.db_pool: DatabasePool | None = None
        self.ai_processor: Optional[AIEventProcessor] = None
        self.doc_summarizer: Optional[DocumentSummarizer] = None
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
            logger.info("AI event processor and document summarizer enabled")
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
    
    async def _enrich_event_with_ai(self, event: Event) -> Event:
        """
        Use AI to validate and enrich an event.
        
        Returns the original or enriched event.
        """
        if not self.ai_processor:
            return event
            
        try:
            # Use AI to normalize the event (clean title, description, categorize)
            enriched = await self.ai_processor.normalize_event(event)
            
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

    async def scrape_source(
        self,
        config,
        source,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> tuple[list, list]:
        """
        Execute a single scraping job.
        
        Args:
            config: City configuration
            source: Source configuration to scrape
            start_date: Optional start date for historical scraping
            end_date: Optional end date for historical scraping
            
        Returns:
            Tuple of (events, documents) for backfill tracking
        """
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
        Download a document, generate AI summary, and update the database.
        
        Args:
            conn: Database connection
            document: Document model
            doc_id: Database ID of the document
            source_name: Name of the source for organizing storage
        """
        if not self.document_downloader:
            return
        
        local_path = None
        
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
        
        # Generate AI summary for the document
        if self.doc_summarizer and self.doc_summarizer.enabled:
            try:
                # Get document type
                doc_type = None
                if hasattr(document, 'doc_type') and document.doc_type:
                    doc_type = document.doc_type.value if hasattr(document.doc_type, 'value') else str(document.doc_type)
                
                # Get content if available
                content_text = None
                if hasattr(document, 'content_markdown') and document.content_markdown:
                    content_text = document.content_markdown
                
                summary = await self.doc_summarizer.generate_summary(
                    title=document.title,
                    document_type=doc_type,
                    content_text=content_text,
                    local_path=local_path,
                )
                
                if summary:
                    await self.db_pool.update_document_ai_summary(
                        conn,
                        doc_id,
                        ai_summary=summary,
                    )
                    logger.info(f"Generated AI summary for document '{document.title}'")
                    
            except Exception as e:
                logger.warning(f"Error generating AI summary for '{document.title}': {e}")

    async def _store_results(self, conn, source, events: list, documents: list) -> None:
        """Store scraped results in database and download documents."""
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
        
        # Track events with documents for summary generation
        events_with_docs = set()
        
        # Store events (with optional AI enrichment)
        for event in events:
            try:
                # Optionally enrich with AI if configured
                if self.ai_processor and self.ai_processor.enabled:
                    event = await self._enrich_event_with_ai(event)
                
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
                        events_with_docs.add(event_id)
                        
                        # Download the document
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
        
        # Use AI to link standalone documents to existing events
        if standalone_doc_ids and self.ai_processor and self.ai_processor.enabled:
            await self._ai_link_documents_to_events(conn, standalone_doc_ids)
        
        # Generate AI summaries for events that have documents
        if events_with_docs and self.ai_processor and self.ai_processor.enabled:
            logger.info(f"Generating AI summaries for {len(events_with_docs)} events with documents...")
            for event_id in events_with_docs:
                await self._generate_event_summary(conn, event_id)
        
        # Update source health status
        await self.db_pool.update_source_health(conn, source_id, success=True)

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
                            await self.scrape_source(config, source)
                            
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
            )
            
            # Log initial queue status
            async with self.db_pool.acquire() as conn:
                status = await self.backfill_manager.get_queue_status(conn)
                logger.info(
                    f"Backfill queue: {status['pending']} pending, "
                    f"{status['completed']} completed, {status['failed']} failed"
                )

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
