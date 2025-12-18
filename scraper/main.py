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
from pipeline.storage import DatabasePool
from pipeline.ai_processor import AIEventProcessor
from pipeline.ai import DocumentSummarizer, GeminiClient
from pipeline.ai.newsletter import NewsletterGenerator, PeriodType, get_period_dates, generate_newsletter_title
from pipeline.backfill import BackfillManager
from pipeline.downloader import DocumentDownloader
from pipeline.document_linker import DocumentLinker
from pipeline.ai_queue import AIQueueProcessor
from pipeline.scraper import ScraperExecutor

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
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300,
            }
        )
        self.db_pool: DatabasePool | None = None
        self.ai_processor: Optional[AIEventProcessor] = None
        self.doc_summarizer: Optional[DocumentSummarizer] = None
        self.newsletter_generator: Optional[NewsletterGenerator] = None
        self.backfill_manager: Optional[BackfillManager] = None
        self.document_downloader: Optional[DocumentDownloader] = None
        self.document_linker: Optional[DocumentLinker] = None
        self.ai_queue: Optional[AIQueueProcessor] = None
        self.scraper: Optional[ScraperExecutor] = None
        self._shutdown_event = asyncio.Event()
        self._configs: list = []

    async def initialize(self) -> None:
        """Initialize database connection pool and processors."""
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
            gemini_client = GeminiClient(api_key=gemini_key)
            self.doc_summarizer = DocumentSummarizer(gemini_client)
            self.newsletter_generator = NewsletterGenerator(gemini_client)
            logger.info("AI processors enabled")
        else:
            logger.info("AI processing disabled (no GEMINI_API_KEY)")

        # Initialize document linker
        self.document_linker = DocumentLinker(self.db_pool, self.ai_processor)

        # Initialize AI queue processor
        self.ai_queue = AIQueueProcessor(
            self.db_pool, self.doc_summarizer, self.ai_processor,
            self.document_linker, self.settings
        )

        # Initialize scraper executor
        self.scraper = ScraperExecutor(
            self.db_pool, self.ai_processor, self.document_downloader
        )

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
        logger.info(f"Backfill manager initialized ({backfill_months} months, {backfill_delay}s delay)")

    async def shutdown(self) -> None:
        """Gracefully shutdown the worker."""
        logger.info("Shutting down worker...")
        self.scheduler.shutdown(wait=False)
        if self.backfill_manager:
            await self.backfill_manager.stop()
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

        # Schedule AI analysis queue
        if self.doc_summarizer and self.doc_summarizer.enabled:
            interval = self.settings.ai_queue_interval_seconds
            self.scheduler.add_job(
                self.process_ai_analysis_queue,
                trigger=CronTrigger(second=f"*/{interval}") if interval < 60 else CronTrigger(minute=f"*/{interval // 60}"),
                id="ai_analysis_queue",
                name="Process AI Analysis Queue",
                replace_existing=True,
            )
            logger.info(f"Scheduled AI analysis queue (every {interval}s)")

        # Schedule manual trigger checker
        self.scheduler.add_job(
            self.process_manual_triggers,
            trigger=CronTrigger(second="*/15"),
            id="manual_trigger_checker",
            name="Check Manual Scrape Triggers",
            replace_existing=True,
        )

        # Schedule newsletters if enabled
        if self.newsletter_generator and self.newsletter_generator.enabled:
            self._schedule_newsletters()

    def _schedule_newsletters(self) -> None:
        """Schedule newsletter generation jobs."""
        self.scheduler.add_job(
            self.generate_newsletter,
            trigger=CronTrigger(hour=6, minute=0),
            id="newsletter_daily",
            name="Generate Daily Newsletter",
            kwargs={"period_type": "daily"},
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.generate_newsletter,
            trigger=CronTrigger(day_of_week="mon", hour=7, minute=0),
            id="newsletter_weekly",
            name="Generate Weekly Newsletter",
            kwargs={"period_type": "weekly"},
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.generate_newsletter,
            trigger=CronTrigger(day=1, hour=8, minute=0),
            id="newsletter_monthly",
            name="Generate Monthly Newsletter",
            kwargs={"period_type": "monthly"},
            replace_existing=True,
        )
        logger.info("Scheduled newsletter generation jobs")

    async def scrape_source(self, config, source, start_date=None, end_date=None, skip_queue_check=False):
        """Execute a scraping job."""
        return await self.scraper.scrape_source(
            config, source, get_driver, start_date, end_date,
            is_busy_callback=self.is_ai_queue_busy,
            skip_queue_check=skip_queue_check,
        )

    async def process_ai_analysis_queue(self) -> None:
        """Process the AI analysis queue."""
        await self.ai_queue.process_queue()

    async def is_ai_queue_busy(self) -> bool:
        """Check if AI queue has pending work."""
        return await self.ai_queue.is_busy()

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

    async def generate_newsletter(self, period_type: str) -> None:
        """Generate a newsletter for the given period."""
        if not self.newsletter_generator or not self.newsletter_generator.enabled:
            return

        try:
            period = PeriodType(period_type)
            start_date, end_date = get_period_dates(period)
            title = generate_newsletter_title(period, end_date)

            logger.info(f"Generating {period_type} newsletter: {title}")

            async with self.db_pool.acquire() as conn:
                # Check for existing newsletter
                existing = await conn.fetchrow("""
                    SELECT id FROM newsletters
                    WHERE period_type = $1 AND period_start = $2 AND period_end = $3
                """, period_type, start_date, end_date)

                if existing:
                    logger.info(f"Newsletter already exists for {period_type} {start_date}-{end_date}")
                    return

                # Fetch events for the period
                events = await conn.fetch("""
                    SELECT e.id, e.title, e.start_time, e.location, e.category,
                           e.ai_summary, e.description
                    FROM events e
                    WHERE e.start_time >= $1 AND e.start_time < $2
                    ORDER BY e.start_time
                """, start_date, end_date)

                if not events:
                    logger.info(f"No events found for {period_type} newsletter")
                    return

                events_data = [
                    {
                        'id': e['id'], 'title': e['title'],
                        'start_time': e['start_time'].isoformat() if e['start_time'] else None,
                        'location': e['location'], 'category': e['category'],
                        'ai_summary': e['ai_summary'], 'description': e['description'],
                    }
                    for e in events
                ]

                content = await self.newsletter_generator.generate(
                    events=events_data, period=period, title=title,
                    start_date=start_date, end_date=end_date,
                )

                if content:
                    await conn.execute("""
                        INSERT INTO newsletters (title, content, period_type, period_start, period_end)
                        VALUES ($1, $2, $3, $4, $5)
                    """, title, content, period_type, start_date, end_date)
                    logger.info(f"Generated {period_type} newsletter: {title}")

        except Exception as e:
            logger.error(f"Error generating {period_type} newsletter: {e}")

    async def _initialize_all_sources(self, configs: list) -> None:
        """Initialize all sources in the database."""
        async with self.db_pool.acquire() as conn:
            for config in configs:
                city_id = config.city_profile.name.lower().replace(" ", "_").replace(",", "")
                all_sources = config.sources + config.private_sources

                for source in all_sources:
                    try:
                        await self.db_pool.get_or_create_source(
                            conn,
                            name=source.name,
                            driver=source.driver,
                            config=source.params,
                            city_id=city_id,
                            is_enabled=source.enabled,
                            schedule=source.schedule,
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
        await self._initialize_all_sources(configs)

        # Schedule jobs
        self.schedule_sources(configs)
        self.scheduler.start()
        logger.info("Scheduler started")

        # Run initial scrape
        if self.settings.run_on_startup:
            logger.info("Running initial scrape...")
            for config in configs:
                for source in config.sources:
                    if source.enabled:
                        try:
                            await self.scrape_source(config, source, skip_queue_check=True)

                            if self.backfill_manager:
                                async with self.db_pool.acquire() as conn:
                                    source_id = await self.db_pool.get_or_create_source(
                                        conn, name=source.name, driver=source.driver,
                                        config=source.params, is_enabled=source.enabled,
                                        schedule=source.schedule,
                                    )
                                    await self.backfill_manager.initialize_queue_for_source(
                                        conn, source_id, source.name
                                    )
                        except Exception as e:
                            logger.error(f"Initial scrape failed for {source.name}: {e}")

        # Start backfill processor
        if self.backfill_manager:
            logger.info("Starting backfill processor...")
            await self.backfill_manager.start_background_processor(
                scrape_callback=self.scrape_source,
                configs=configs,
                ai_queue_check_callback=self.is_ai_queue_busy,
            )

        # Run initial AI queue processing
        if self.doc_summarizer and self.doc_summarizer.enabled:
            logger.info("Running initial AI analysis...")
            await self.process_ai_analysis_queue()

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
