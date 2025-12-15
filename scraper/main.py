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
            logger.info("AI event processor enabled")
        else:
            logger.info("AI event processor disabled (no GEMINI_API_KEY)")
        
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
        
        # Get upcoming events for matching (next 90 days)
        cutoff = datetime.now() + timedelta(days=90)
        events = await conn.fetch("""
            SELECT id, title, start_time, description
            FROM events
            WHERE start_time >= NOW() - INTERVAL '7 days'
              AND start_time <= $1
            ORDER BY start_time
        """, cutoff)
        
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
                # Format document date if available
                doc_date = None
                if hasattr(document, 'published_at') and document.published_at:
                    doc_date = document.published_at.strftime('%Y-%m-%d')
                
                # Get local path if downloaded (stored as file_path in Document model)
                local_path = None
                if hasattr(document, 'file_path') and document.file_path:
                    local_path = document.file_path
                
                # Get content - Document model uses content_markdown, not content
                doc_content = None
                if hasattr(document, 'content_markdown') and document.content_markdown:
                    doc_content = document.content_markdown
                
                # Use AI to find related events
                matches = await self.ai_processor.find_related_events(
                    document_title=document.title,
                    document_content=doc_content,
                    events=events_list,
                    document_date=doc_date,
                    document_type=document.doc_type.value if hasattr(document, 'doc_type') and document.doc_type else None,
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
                    
            except Exception as e:
                logger.warning(f"AI document linking failed for '{document.title}': {e}")

    async def _download_and_update_document(
        self,
        conn,
        document: Document,
        doc_id: int,
        source_name: str,
    ) -> None:
        """
        Download a document and update its local path in the database.
        
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
                # Update document with local path
                await self.db_pool.update_document_local_path(
                    conn,
                    doc_id,
                    local_path=result["local_path"],
                    file_size_bytes=result.get("file_size"),
                    mime_type=result.get("mime_type"),
                    file_hash=result.get("file_hash"),
                )
                logger.debug(f"Downloaded document '{document.title}' -> {result['local_path']}")
            elif result is None:
                logger.debug(f"Skipped download for '{document.title}' (not downloadable)")
                
        except Exception as e:
            logger.warning(f"Error downloading '{document.title}': {e}")

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
        )
        
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
        
        # Update source health status
        await self.db_pool.update_source_health(conn, source_id, success=True)

    async def run(self) -> None:
        """Main run loop."""
        await self.initialize()

        # Load all city configurations
        configs_dir = Path(self.settings.configs_dir)
        configs = load_all_configs(configs_dir)
        self._configs = configs  # Store for backfill access
        logger.info(f"Loaded {len(configs)} city configuration(s)")

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
