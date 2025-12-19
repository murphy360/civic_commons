"""
Scraper execution and result storage.

Handles running drivers and persisting results to the database.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from models import Document, Event

logger = logging.getLogger("civic.scraper")


class ScraperExecutor:
    """Executes scraping jobs and stores results."""

    def __init__(self, db_pool, ai_processor=None, document_downloader=None):
        self.db_pool = db_pool
        self.ai_processor = ai_processor
        self.document_downloader = document_downloader

    async def scrape_source(
        self,
        config,
        source,
        get_driver,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        is_busy_callback=None,
        skip_queue_check: bool = False,
    ) -> tuple[list, list]:
        """
        Execute a single scraping job.
        
        Args:
            config: City configuration
            source: Source configuration to scrape
            get_driver: Function to get driver class by name
            start_date: Optional start date for historical scraping
            end_date: Optional end date for historical scraping
            is_busy_callback: Callback to check if AI queue is busy
            skip_queue_check: If True, skip AI queue busy check
            
        Returns:
            Tuple of (events, documents) for backfill tracking
        """
        if not skip_queue_check and is_busy_callback and await is_busy_callback():
            logger.info(f"Skipping scrape for {source.name} - AI queue has pending work")
            return [], []

        date_range = ""
        if start_date and end_date:
            date_range = f" ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})"
        logger.info(f"Starting scrape: {config.city_profile.name} / {source.name}{date_range}")

        events = []
        documents = []

        try:
            driver_class = get_driver(source.driver)

            driver_params = dict(source.params) if source.params else {}
            if start_date and end_date:
                driver_params["start_date"] = start_date
                driver_params["end_date"] = end_date
                driver_params["backfill_mode"] = True

            driver = driver_class(
                source_config=source,
                city_config=config,
                params_override=driver_params,
            )

            events, documents = await driver.fetch()

            if self.db_pool:
                async with self.db_pool.acquire() as conn:
                    # Generate city_id from city name (same logic as main.py)
                    city_id = config.city_profile.name.lower().replace(" ", "_").replace(",", "")
                    await self._store_results(
                        conn=conn,
                        source=source,
                        events=events,
                        documents=documents,
                        city_id=city_id,
                        city_name=config.city_profile.name,
                    )

            logger.info(f"Completed scrape: {source.name} - {len(events)} events, {len(documents)} documents")
            return events, documents

        except Exception as e:
            logger.error(f"Scrape failed: {source.name} - {e}")
            raise

    async def _store_results(self, conn, source, events: list, documents: list, city_id: str, city_name: str = "") -> None:
        """Store scraped results in database and download documents."""
        if not events and not documents:
            return

        source_id = await self.db_pool.get_or_create_source(
            conn,
            name=source.name,
            driver=source.driver,
            config=source.params,
            city_id=city_id,
            is_enabled=source.enabled,
            schedule=source.schedule,
        )

        # Store events
        for event in events:
            try:
                if self.ai_processor and self.ai_processor.enabled:
                    event = await self._enrich_event_with_ai(event, city_name)

                event_id = await self.db_pool.upsert_event(
                    conn, source_id, event, ai_processor=self.ai_processor
                )
                logger.debug(f"Stored event: {event.title} -> {event_id}")

                for document in event.documents:
                    try:
                        doc_id = await self.db_pool.upsert_document(
                            conn, source_id, document, event_id=event_id
                        )
                        await self._download_document(conn, document, doc_id, source.name)
                    except Exception as e:
                        logger.error(f"Failed to store event document '{document.title}': {e}")

            except Exception as e:
                logger.error(f"Failed to store event '{event.title}': {e}")

        # Store standalone documents
        for document in documents:
            try:
                doc_id = await self.db_pool.upsert_document(conn, source_id, document)
                logger.debug(f"Stored standalone document: {document.title} -> {doc_id}")
                await self._download_document(conn, document, doc_id, source.name)
            except Exception as e:
                logger.error(f"Failed to store document '{document.title}': {e}")

        await self.db_pool.update_source_health(conn, source_id, success=True)
        logger.info(f"Completed storing results for {source.name}: {len(events)} events, {len(documents)} documents")

    async def _enrich_event_with_ai(self, event: Event, city_name: str = "") -> Event:
        """Use AI to normalize event data."""
        if not self.ai_processor or not self.ai_processor.enabled:
            return event

        try:
            normalized = await self.ai_processor.normalize_event(event, city_name=city_name)
            if normalized:
                if normalized.title:
                    event.title = normalized.title
                if normalized.category:
                    event.category = normalized.category
                if normalized.description:
                    event.description = normalized.description
        except Exception as e:
            logger.warning(f"AI enrichment failed for '{event.title}': {e}")

        return event

    async def _download_document(self, conn, document: Document, doc_id: int, source_name: str) -> None:
        """Download a document and update the database."""
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
                await self.db_pool.update_document_local_path(
                    conn,
                    doc_id,
                    local_path=result["local_path"],
                    file_size_bytes=result.get("file_size"),
                    mime_type=result.get("mime_type"),
                    file_hash=result.get("file_hash"),
                )
                logger.debug(f"Downloaded document '{document.title}' -> {result['local_path']}")

        except Exception as e:
            logger.warning(f"Error downloading '{document.title}': {e}")

    async def link_documents_to_events(self, conn, documents: list[tuple[int, Document]]) -> None:
        """Use AI to link standalone documents to events."""
        past_cutoff = datetime.now() - timedelta(days=365)
        future_cutoff = datetime.now() + timedelta(days=90)

        events = await conn.fetch("""
            SELECT id, title, start_time, description
            FROM events
            WHERE start_time >= $1 AND start_time <= $2
            ORDER BY start_time
        """, past_cutoff, future_cutoff)

        if not events:
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
                doc_date = None
                if hasattr(document, 'meeting_date') and document.meeting_date:
                    doc_date = document.meeting_date.strftime('%Y-%m-%d')
                elif hasattr(document, 'published_at') and document.published_at:
                    doc_date = document.published_at.strftime('%Y-%m-%d')

                local_path = getattr(document, 'file_path', None)
                doc_content = getattr(document, 'content_markdown', None)

                doc_type_str = None
                if hasattr(document, 'doc_type') and document.doc_type:
                    doc_type_str = str(document.doc_type.value) if hasattr(document.doc_type, 'value') else str(document.doc_type)

                matches = await self.ai_processor.find_related_events(
                    document_title=document.title,
                    document_content=doc_content,
                    events=events_list,
                    document_date=doc_date,
                    document_type=doc_type_str,
                    local_path=local_path,
                )

                for match in matches:
                    await conn.execute("""
                        INSERT INTO event_documents (event_id, document_id, relationship)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (event_id, document_id) DO NOTHING
                    """, match['event_id'], doc_id, match.get('relationship', 'attachment'))

                if matches:
                    logger.info(f"AI linked document '{document.title}' to {len(matches)} events")

            except Exception as e:
                logger.warning(f"AI document linking failed for '{document.title}': {e}")
