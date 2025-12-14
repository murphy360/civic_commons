"""
Purpose: Main entrypoint for the scraper worker service
Dependencies: asyncio, APScheduler for cron scheduling, config module for YAML loading
Consumed by: Docker container entrypoint, direct execution for development
Side effects: Schedules and executes scraping jobs, writes to PostgreSQL
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import load_all_configs, Settings
from drivers import get_driver
from pipeline.storage import DatabasePool

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
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.scheduler = AsyncIOScheduler()
        self.db_pool: DatabasePool | None = None
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> None:
        """Initialize database connection pool."""
        logger.info("Initializing database connection pool...")
        self.db_pool = await DatabasePool.create(self.settings.get_database_url())
        logger.info("Database pool initialized")

    async def shutdown(self) -> None:
        """Graceful shutdown of all resources."""
        logger.info("Shutting down worker...")
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
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

    async def scrape_source(self, config, source) -> None:
        """
        Execute a single scraping job.
        
        Args:
            config: City configuration
            source: Source configuration to scrape
        """
        logger.info(f"Starting scrape: {config.city_profile.name} / {source.name}")
        
        try:
            # Get the appropriate driver
            driver_class = get_driver(source.driver)
            driver = driver_class(
                source_config=source,
                city_config=config,
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

        except Exception as e:
            logger.error(f"Scrape failed: {source.name} - {e}", exc_info=True)
            # TODO: Update source health status in database
            raise

    async def _store_results(self, conn, source, events: list, documents: list) -> None:
        """Store scraped results in database."""
        # TODO: Implement storage logic
        # - Upsert events (dedup by source + external ID)
        # - Upsert documents (dedup by content hash)
        # - Update source health status
        pass

    async def run(self) -> None:
        """Main run loop."""
        await self.initialize()

        # Load all city configurations
        configs_dir = Path(self.settings.configs_dir)
        configs = load_all_configs(configs_dir)
        logger.info(f"Loaded {len(configs)} city configuration(s)")

        # Schedule all sources
        self.schedule_sources(configs)

        # Start the scheduler
        self.scheduler.start()
        logger.info("Scheduler started. Waiting for jobs...")

        # Run initial scrape for all sources (optional)
        if self.settings.run_on_startup:
            logger.info("Running initial scrape for all sources...")
            for config in configs:
                for source in config.sources:
                    await self.scrape_source(config, source)

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
