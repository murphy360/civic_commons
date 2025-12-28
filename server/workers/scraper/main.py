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
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import load_all_configs, Settings
from drivers import get_driver
from models import Event, Document
from mcp_client import MCPClient, get_mcp_client, close_mcp_client
from pipeline.storage import DatabasePool
from pipeline.downloader import DocumentDownloader
from pipeline.scraper import ScraperExecutor
from pipeline.queue_manager import QueueManager
from pipeline.queue_processor import QueueProcessor
from pipeline.activity_logger_http import ActivityLoggerHTTP as ActivityLogger, LogLevel, LogCategory

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
    - Execute drivers and store results (discovery, download, extraction)
    - Handle graceful shutdown
    
    NOTE: AI processing and document-to-event linking are handled by
    the Cascade service, not this scraper.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300,
            }
        )
        self.db_pool: DatabasePool | None = None
        self.document_downloader: Optional[DocumentDownloader] = None
        self.scraper: Optional[ScraperExecutor] = None
        self.queue_manager: Optional[QueueManager] = None
        self.queue_processor: Optional[QueueProcessor] = None
        self.activity_logger: Optional[ActivityLogger] = None
        self.mcp_client: Optional[MCPClient] = None
        self._shutdown_event = asyncio.Event()
        self._configs: list = []

    async def initialize(self) -> None:
        """Initialize database connection pool and processors."""
        logger.info("Initializing database connection pool...")
        
        # Initialize HTTP-based activity logger (uses centralized API)
        self.activity_logger = ActivityLogger()
        await self.activity_logger.log_system_started()
        logger.info("Activity logger initialized (HTTP client)")
        
        # Now create DatabasePool with activity logger
        self.db_pool = await DatabasePool.create(
            self.settings.get_database_url(),
            activity_logger=self.activity_logger
        )
        logger.info("Database pool initialized")

        # Initialize MCP client for unified event management
        try:
            self.mcp_client = await get_mcp_client(base_url=self.settings.mcp_url)
            logger.info(f"MCP client connected to {self.settings.mcp_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to MCP server at {self.settings.mcp_url}: {e}. Falling back to direct DB.")
            self.mcp_client = None

        # Initialize document downloader
        download_dir = os.getenv("DOCUMENT_STORAGE_DIR", "/data/documents")
        self.document_downloader = DocumentDownloader(storage_dir=Path(download_dir))
        logger.info(f"Document downloader initialized (storage: {download_dir})")

        # AI processing and document linking handled by the Cascade service
        logger.info("AI processing and document linking delegated to Cascade service")

        # Initialize unified queue manager
        self.queue_manager = QueueManager(self.db_pool)
        logger.info("Queue manager initialized")

        # Initialize scraper executor (now uses queue_manager)
        self.scraper = ScraperExecutor(
            self.db_pool, self.document_downloader, 
            queue_manager=self.queue_manager,
            activity_logger=self.activity_logger,
            mcp_client=self.mcp_client,
            api_url="http://commons-api:8080",
        )

        # Initialize unified queue processor
        self.queue_processor = QueueProcessor(
            db_pool=self.db_pool,
            queue_manager=self.queue_manager,
            document_downloader=self.document_downloader,
            settings=self.settings,
            activity_logger=self.activity_logger,
        )
        logger.info("Queue processor initialized")

        # Cascade logic moved to MCP server

    async def shutdown(self) -> None:
        """Gracefully shutdown the worker."""
        logger.info("Shutting down worker...")
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if self.db_pool:
            await self.db_pool.close()
        self._shutdown_event.set()
        logger.info("Worker shutdown complete")

    def schedule_sources(self, configs: list) -> None:
        """Schedule all sources from loaded configurations."""
        self._configs = configs

        for config in configs:
            city_name = config.city_profile.name

            for source in config.sources:
                if not source.enabled:
                    logger.info(f"Skipping disabled source: {city_name}:{source.name}")
                    continue

                job_id = f"{city_name}:{source.name}"
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
                    kwargs={"config": config, "source": source},
                    replace_existing=True,
                )
                logger.info(f"Scheduled job: {job_id} ({source.schedule})")

        # AI analysis is handled by the Cascade service
        # Schedule download queue processing (every 30 seconds)
        self.scheduler.add_job(
            self.process_download_queue,
            trigger=CronTrigger(second="*/30"),
            id="download_queue",
            name="Process Download Queue",
            replace_existing=True,
        )
        logger.info("Scheduled download queue (every 30s)")

        # Schedule extraction queue processing (every 30 seconds)
        self.scheduler.add_job(
            self.process_extraction_queue,
            trigger=CronTrigger(second="*/30"),
            id="extraction_queue",
            name="Process Extraction Queue",
            replace_existing=True,
        )
        logger.info("Scheduled extraction queue (every 30s)")

        # Schedule queue maintenance (every 5 minutes)
        self.scheduler.add_job(
            self.process_queue_maintenance,
            trigger=CronTrigger(minute="*/5"),
            id="queue_maintenance",
            name="Queue Maintenance",
            replace_existing=True,
        )
        logger.info("Scheduled queue maintenance (every 5 min)")

        # Schedule manual trigger checker
        self.scheduler.add_job(
            self.process_manual_triggers,
            trigger=CronTrigger(second="*/15"),
            id="manual_trigger_checker",
            name="Check Manual Scrape Triggers",
            replace_existing=True,
        )
        # Summary regeneration now handled by MCP server

    def _schedule_summary_jobs(self) -> None:
        """Schedule summary regeneration jobs."""
        # Process stale summaries every 5 minutes
        self.scheduler.add_job(
            self.process_stale_summaries,
            trigger=CronTrigger(minute="*/5"),
            id="summary_regeneration",
            name="Regenerate Stale Summaries",
            replace_existing=True,
        )
        logger.info("Scheduled summary regeneration job (every 5 min)")

    async def scrape_source(self, config, source, start_date=None, end_date=None, skip_queue_check=False):
        """Execute a scraping job."""
        return await self.scraper.scrape_source(
            config, source, get_driver, start_date, end_date,
            skip_queue_check=skip_queue_check,
        )

    async def process_download_queue(self) -> None:
        """Process the download queue."""
        if self.queue_processor:
            await self.queue_processor.process_downloads()

    async def process_extraction_queue(self) -> None:
        """Process the extraction queue."""
        if self.queue_processor:
            await self.queue_processor.process_extractions()

    async def process_queue_maintenance(self) -> None:
        """Run queue maintenance tasks."""
        if self.queue_processor:
            stats = await self.queue_processor.run_maintenance()
            if stats.get("stuck_reset", 0) > 0 or stats.get("failed_retried", 0) > 0:
                logger.info(f"Queue maintenance: reset {stats['stuck_reset']} stuck, retried {stats['failed_retried']} failed")

    async def process_manual_triggers(self) -> None:
        """Check for and process manually triggered scrapes."""
        try:
            async with self.db_pool.acquire() as conn:
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
                    config, source = self._find_config_for_source(row['name'], row['city_id'])
                    if config and source:
                        logger.info(f"Manual trigger: Running scrape for {row['name']}")
                        try:
                            await self.scrape_source(config, source, skip_queue_check=True)
                        except Exception as e:
                            logger.error(f"Manual trigger error for {row['name']}: {e}")
                    else:
                        logger.warning(f"Manual trigger: Config not found for {row['name']}")
                        await conn.execute(
                            "UPDATE sources SET trigger_requested_at = NULL WHERE id = $1",
                            row['id']
                        )
        except Exception as e:
            logger.error(f"Manual trigger check error: {e}")

    def _find_config_for_source(self, source_name: str, city_id: str):
        """Find matching config and source for a triggered scrape."""
        for config in self._configs:
            config_city_id = config.city_profile.name.lower().replace(' ', '_').replace(',', '')
            db_city_id = city_id.lower().replace(' ', '_').replace(',', '')

            if config_city_id == db_city_id or db_city_id.startswith(config_city_id.split('_')[0]):
                for source in config.sources:
                    if source.name == source_name:
                        return config, source
        return None, None

    async def process_stale_summaries(self) -> None:
        """Process summaries that have been marked as stale.
        
        NOTE: Summary regeneration is now handled by the MCP server.
        This method is kept as a no-op for backward compatibility.
        """
        pass

    async def _initialize_database(self, configs: list) -> None:
        """Initialize all cities, entities, and sources in the database from config."""
        async with self.db_pool.acquire() as conn:
            for config in configs:
                city_id = config.city_profile.name.lower().replace(" ", "_").replace(",", "")
                
                # Create/update city from config
                display_name = config.city_profile.name
                assistant_name = getattr(config.assistant, 'name', None) if hasattr(config, 'assistant') else None
                assistant_persona = getattr(config.assistant, 'persona', None) if hasattr(config, 'assistant') else None
                timezone = config.city_profile.timezone  # Required from config
                
                await self.db_pool.get_or_create_city(
                    conn,
                    city_id=city_id,
                    display_name=display_name,
                    assistant_name=assistant_name,
                    assistant_persona=assistant_persona,
                    timezone=timezone,
                )
                
                # Sync entities from config (must happen before sources)
                entity_id_map = {}
                if config.entities:
                    entity_id_map = await self.db_pool.sync_entities(conn, city_id, config.entities)
                
                # Sync color schemes from config
                if config.color_schemes:
                    await self.db_pool.sync_color_schemes(conn, city_id, config.color_schemes)
                
                # Initialize sources with entity references
                all_sources = config.sources + config.private_sources

                for source in all_sources:
                    try:
                        # Look up entity_id from entity_key
                        entity_id = entity_id_map.get(source.entity) if source.entity else None
                        
                        await self.db_pool.get_or_create_source(
                            conn,
                            name=source.name,
                            driver=source.driver,
                            config=source.params,
                            city_id=city_id,
                            is_enabled=source.enabled,
                            schedule=source.schedule,
                            entity_id=entity_id,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to initialize source '{source.name}': {e}")

        logger.info(f"Initialized sources from {len(configs)} config(s)")

    async def run(self) -> None:
        """Main run loop."""
        await self.initialize()

        # Load configurations
        configs_dir = Path(self.settings.configs_dir)
        configs = load_all_configs(configs_dir)
        self._configs = configs
        logger.info(f"Loaded {len(configs)} city configuration(s)")

        # Initialize sources in database
        await self._initialize_database(configs)

        # Schedule jobs
        self.schedule_sources(configs)
        self.scheduler.start()
        logger.info("Scheduler started")

        logger.info("=" * 60)
        logger.info("SCRAPER SERVICE STARTED - Ready for scheduled jobs")
        logger.info("=" * 60)
        
        # Log to activity log
        await self.activity_logger.log(
            LogLevel.SUCCESS,
            LogCategory.SYSTEM,
            "startup",
            "SCRAPER SERVICE STARTED - Ready for scheduled jobs",
        )

        # Run initial scrape
        if self.settings.run_on_startup:
            logger.info("Running initial scrape...")
            for config in configs:
                city_id = config.city_profile.name.lower().replace(" ", "_").replace(",", "")
                for source in config.sources:
                    if source.enabled:
                        try:
                            await self.scrape_source(config, source, skip_queue_check=True)
                        except Exception as e:
                            logger.error(f"Initial scrape failed for {source.name}: {e}")

        # AI processing handled by Cascade service

        # Wait for shutdown
        await self._shutdown_event.wait()


async def main() -> None:
    """Application entrypoint."""
    settings = Settings()
    worker = Worker(settings)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.shutdown()))

    try:
        await worker.run()
    except KeyboardInterrupt:
        pass
    finally:
        await worker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

