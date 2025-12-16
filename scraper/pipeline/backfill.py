"""
Purpose: Historical data backfill manager for incremental scraping of past events
Dependencies: asyncpg for PostgreSQL, datetime for date handling
Consumed by: main.py worker
Side effects: Creates and processes backfill queue in database

Strategy:
1. On first run: Scrape future events + 7 days of past events (fast startup)
2. Queue historical months for incremental processing
3. Process queue items one at a time during idle periods to avoid taxing resources
4. Track progress per source to allow resumption after restarts
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("civic.backfill")


class BackfillStatus(str, Enum):
    """Status of a backfill queue item."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class BackfillJob:
    """A single backfill job for a specific time period."""
    id: int
    source_id: int
    source_name: str
    start_date: datetime
    end_date: datetime
    status: BackfillStatus
    priority: int  # Lower = higher priority
    attempts: int
    last_error: Optional[str]
    created_at: datetime


class BackfillManager:
    """
    Manages incremental historical data backfill.
    
    Design principles:
    - Non-blocking: Backfill runs during idle time, not blocking regular scrapes
    - Incremental: Process one month at a time to limit resource usage
    - Resumable: Track progress in database, survive restarts
    - Rate-limited: Configurable delay between backfill operations
    """
    
    # Default settings
    DEFAULT_INITIAL_DAYS_BACK = 7  # Days of history on first run
    DEFAULT_BACKFILL_MONTHS = 12  # How many months of history to eventually backfill
    DEFAULT_BATCH_DELAY_SECONDS = 300  # 5 minutes between backfill batches
    DEFAULT_ITEMS_PER_BATCH = 1  # Process 1 source-month at a time
    
    def __init__(
        self,
        db_pool,
        initial_days_back: int = DEFAULT_INITIAL_DAYS_BACK,
        backfill_months: int = DEFAULT_BACKFILL_MONTHS,
        batch_delay_seconds: int = DEFAULT_BATCH_DELAY_SECONDS,
        items_per_batch: int = DEFAULT_ITEMS_PER_BATCH,
    ):
        self.db_pool = db_pool
        self.initial_days_back = initial_days_back
        self.backfill_months = backfill_months
        self.batch_delay_seconds = batch_delay_seconds
        self.items_per_batch = items_per_batch
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ai_queue_check = None  # Set by start_background_processor
    
    async def ensure_tables_exist(self, conn) -> None:
        """Create backfill tracking tables if they don't exist."""
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS backfill_queue (
                id SERIAL PRIMARY KEY,
                source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 100,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                events_found INTEGER,
                documents_found INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                UNIQUE(source_id, start_date, end_date)
            );
            
            CREATE INDEX IF NOT EXISTS backfill_queue_status_idx 
                ON backfill_queue(status, priority, created_at);
            CREATE INDEX IF NOT EXISTS backfill_queue_source_idx 
                ON backfill_queue(source_id);
        """)
        logger.debug("Backfill tables ensured")
    
    async def initialize_queue_for_source(
        self,
        conn,
        source_id: int,
        source_name: str,
    ) -> int:
        """
        Initialize backfill queue for a source if not already done.
        
        Creates queue entries for historical months, starting from
        most recent (higher priority) to oldest (lower priority).
        
        Returns:
            Number of queue items created
        """
        # Check if already initialized
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM backfill_queue WHERE source_id = $1",
            source_id,
        )
        
        if existing > 0:
            logger.debug(f"Backfill queue already exists for {source_name}")
            return 0
        
        # Calculate date ranges for each month
        today = datetime.now().date()
        items_created = 0
        
        # Start from 1 week ago (skip the initial_days_back already covered)
        # and go back backfill_months months
        start_of_backfill = today - timedelta(days=self.initial_days_back)
        
        for month_offset in range(self.backfill_months):
            # Calculate month boundaries
            # Each entry covers a calendar month
            reference_date = start_of_backfill - timedelta(days=30 * month_offset)
            
            # First day of the month
            month_start = reference_date.replace(day=1)
            
            # Last day of the month
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)
            
            # Don't include dates in the future or already covered
            if month_end >= start_of_backfill:
                month_end = start_of_backfill - timedelta(days=1)
            
            if month_start > month_end:
                continue  # Skip if range is invalid
            
            # Priority: more recent months have higher priority (lower number)
            priority = month_offset + 1
            
            try:
                await conn.execute(
                    """
                    INSERT INTO backfill_queue 
                        (source_id, start_date, end_date, status, priority)
                    VALUES ($1, $2, $3, 'pending', $4)
                    ON CONFLICT (source_id, start_date, end_date) DO NOTHING
                    """,
                    source_id,
                    month_start,
                    month_end,
                    priority,
                )
                items_created += 1
            except Exception as e:
                logger.warning(f"Failed to create backfill entry: {e}")
        
        if items_created > 0:
            logger.info(
                f"Created {items_created} backfill queue items for {source_name} "
                f"({self.backfill_months} months of history)"
            )
        
        return items_created
    
    async def get_next_pending_job(self, conn) -> Optional[BackfillJob]:
        """
        Get the next pending backfill job.
        
        Returns highest priority (lowest number) pending job that
        hasn't been attempted too many times.
        """
        row = await conn.fetchrow(
            """
            SELECT 
                bq.id, bq.source_id, s.name as source_name,
                bq.start_date, bq.end_date, bq.status, 
                bq.priority, bq.attempts, bq.last_error, bq.created_at
            FROM backfill_queue bq
            JOIN sources s ON s.id = bq.source_id
            WHERE bq.status = 'pending' 
                AND bq.attempts < 3
            ORDER BY bq.priority ASC, bq.created_at ASC
            LIMIT 1
            """,
        )
        
        if not row:
            return None
        
        return BackfillJob(
            id=row["id"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            status=BackfillStatus(row["status"]),
            priority=row["priority"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            created_at=row["created_at"],
        )
    
    async def mark_job_started(self, conn, job_id: int) -> None:
        """Mark a backfill job as in progress."""
        await conn.execute(
            """
            UPDATE backfill_queue SET
                status = 'in_progress',
                started_at = NOW(),
                attempts = attempts + 1
            WHERE id = $1
            """,
            job_id,
        )
    
    async def mark_job_completed(
        self,
        conn,
        job_id: int,
        events_found: int = 0,
        documents_found: int = 0,
    ) -> None:
        """Mark a backfill job as completed."""
        await conn.execute(
            """
            UPDATE backfill_queue SET
                status = 'completed',
                completed_at = NOW(),
                events_found = $2,
                documents_found = $3,
                last_error = NULL
            WHERE id = $1
            """,
            job_id,
            events_found,
            documents_found,
        )
    
    async def mark_job_failed(
        self,
        conn,
        job_id: int,
        error: str,
    ) -> None:
        """Mark a backfill job as failed (will be retried if under max attempts)."""
        # Check current attempts
        row = await conn.fetchrow(
            "SELECT attempts FROM backfill_queue WHERE id = $1",
            job_id,
        )
        
        new_status = "pending" if row and row["attempts"] < 3 else "failed"
        
        await conn.execute(
            """
            UPDATE backfill_queue SET
                status = $2,
                last_error = $3
            WHERE id = $1
            """,
            job_id,
            new_status,
            error[:500] if error else None,  # Truncate error message
        )
    
    async def get_queue_status(self, conn) -> dict:
        """Get summary of backfill queue status."""
        rows = await conn.fetch(
            """
            SELECT 
                status, 
                COUNT(*) as count,
                COALESCE(SUM(events_found), 0) as total_events,
                COALESCE(SUM(documents_found), 0) as total_documents
            FROM backfill_queue
            GROUP BY status
            """
        )
        
        status = {
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
            "total_events": 0,
            "total_documents": 0,
        }
        
        for row in rows:
            status[row["status"]] = row["count"]
            if row["status"] == "completed":
                status["total_events"] = row["total_events"]
                status["total_documents"] = row["total_documents"]
        
        return status
    
    async def start_background_processor(
        self,
        scrape_callback,
        configs: list,
        ai_queue_check_callback=None,
    ) -> None:
        """
        Start the background backfill processor.
        
        Args:
            scrape_callback: Async function to call for scraping
                            Signature: (config, source, start_date, end_date) -> (events, documents)
            configs: List of city configurations
            ai_queue_check_callback: Optional async function to check if AI queue is busy
                                    Signature: () -> bool (True if busy)
        """
        if self._running:
            logger.warning("Backfill processor already running")
            return
        
        self._running = True
        self._ai_queue_check = ai_queue_check_callback
        self._task = asyncio.create_task(
            self._process_queue(scrape_callback, configs)
        )
        logger.info("Backfill background processor started")
    
    async def stop(self) -> None:
        """Stop the background processor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Backfill processor stopped")
    
    async def _process_queue(
        self,
        scrape_callback,
        configs: list,
    ) -> None:
        """Background task that processes the backfill queue."""
        # Initial delay before starting backfill
        await asyncio.sleep(60)  # Wait 1 minute after startup
        
        while self._running:
            try:
                # Check if AI queue is busy - if so, wait
                if self._ai_queue_check and await self._ai_queue_check():
                    logger.info("Backfill: AI queue busy, waiting...")
                    await asyncio.sleep(self.batch_delay_seconds)
                    continue
                
                async with self.db_pool.acquire() as conn:
                    # Get next job
                    job = await self.get_next_pending_job(conn)
                    
                    if not job:
                        # Queue is empty or all done, check again later
                        status = await self.get_queue_status(conn)
                        if status["pending"] == 0 and status["in_progress"] == 0:
                            logger.info(
                                f"Backfill complete: {status['completed']} completed, "
                                f"{status['failed']} failed, "
                                f"{status['total_events']} events, "
                                f"{status['total_documents']} documents"
                            )
                            # Check less frequently when done
                            await asyncio.sleep(3600)  # 1 hour
                        else:
                            await asyncio.sleep(self.batch_delay_seconds)
                        continue
                    
                    # Mark as in progress
                    await self.mark_job_started(conn, job.id)
                    
                    logger.info(
                        f"Processing backfill: {job.source_name} "
                        f"({job.start_date} to {job.end_date})"
                    )
                    
                    try:
                        # Find the config and source for this job
                        config, source = self._find_source_config(
                            configs, job.source_id, job.source_name
                        )
                        
                        if not config or not source:
                            logger.warning(
                                f"Could not find config for source {job.source_name}"
                            )
                            await self.mark_job_failed(
                                conn, job.id, "Source configuration not found"
                            )
                            continue
                        
                        # Execute the backfill scrape
                        events, documents = await scrape_callback(
                            config=config,
                            source=source,
                            start_date=job.start_date,
                            end_date=job.end_date,
                        )
                        
                        # Mark completed
                        await self.mark_job_completed(
                            conn, job.id,
                            events_found=len(events),
                            documents_found=len(documents),
                        )
                        
                        logger.info(
                            f"Backfill completed: {job.source_name} - "
                            f"{len(events)} events, {len(documents)} documents"
                        )
                        
                    except Exception as e:
                        logger.error(f"Backfill job failed: {e}")
                        await self.mark_job_failed(conn, job.id, str(e))
                
                # Delay between jobs
                await asyncio.sleep(self.batch_delay_seconds)
                
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Backfill processor error: {e}")
                await asyncio.sleep(60)  # Wait before retrying
    
    def _find_source_config(
        self,
        configs: list,
        source_id: int,
        source_name: str,
    ):
        """Find the config and source objects for a backfill job."""
        for config in configs:
            for source in config.sources:
                if source.name == source_name:
                    return config, source
        return None, None
