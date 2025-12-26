"""
Scraper execution and result storage.

Handles running drivers and persisting results to the database.
Documents are registered as "discovered" immediately (visible in UI),
then processed asynchronously through the queue system.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.activity_logger import ActivityLogger

from models import Document, Event
from .queue_manager import QueueManager, ContentStatus

logger = logging.getLogger("civic.scraper")


class ScraperExecutor:
    """Executes scraping jobs and stores results."""

    def __init__(self, db_pool, ai_processor=None, document_downloader=None, 
                 queue_manager: QueueManager = None,
                 activity_logger: Optional["ActivityLogger"] = None,
                 mcp_client=None):
        self.db_pool = db_pool
        self.ai_processor = ai_processor
        self.document_downloader = document_downloader
        self.queue_manager = queue_manager
        self.activity = activity_logger
        self.mcp_client = mcp_client

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

            # Log scrape started
            source_id = None
            if self.db_pool:
                async with self.db_pool.acquire() as conn:
                    source_id = await conn.fetchval("""
                        SELECT id FROM sources WHERE name = $1 AND city_id = $2 LIMIT 1
                    """, source.name, config.city_profile.name.lower().replace(" ", "_").replace(",", ""))
            
            if self.activity and source_id:
                await self.activity.log_scrape_started(
                    source_id, source.name,
                    city_id=config.city_profile.name.lower().replace(" ", "_").replace(",", ""),
                )

            events, documents = await driver.fetch()

            if self.db_pool:
                async with self.db_pool.acquire() as conn:
                    # Generate city_id from city name (same logic as main.py)
                    city_id = config.city_profile.name.lower().replace(" ", "_").replace(",", "")
                    
                    # Look up entity_id from source's entity reference
                    entity_id = None
                    if source.entity:
                        entity_id = await self.db_pool.get_entity_id(conn, city_id, source.entity)
                    
                    await self._store_results(
                        conn=conn,
                        source=source,
                        events=events,
                        documents=documents,
                        city_id=city_id,
                        city_name=config.city_profile.name,
                        mcp_client=self.mcp_client,
                        entity_id=entity_id,
                        data_start_date=config.get_data_start_date(),
                    )

            logger.info(f"Completed scrape: {source.name} - {len(events)} events, {len(documents)} documents")
            
            # Log scrape completed
            if self.activity and source_id:
                await self.activity.log_scrape_completed(
                    source_id, source.name,
                    events_found=len(events),
                    documents_found=len(documents),
                    city_id=config.city_profile.name.lower().replace(" ", "_").replace(",", ""),
                )
            
            return events, documents

        except Exception as e:
            logger.error(f"Scrape failed: {source.name} - {e}")
            
            # Log scrape failed
            if self.activity:
                await self.activity.log_scrape_failed(
                    source_id or 0, source.name, str(e),
                    city_id=config.city_profile.name.lower().replace(" ", "_").replace(",", ""),
                )
            raise

    async def _store_results(self, conn, source, events: list, documents: list, city_id: str, city_name: str = "", mcp_client=None, entity_id: int | None = None, data_start_date: datetime | None = None) -> None:
        """
        Store scraped results in database.
        
        Documents are registered as "discovered" - immediately visible in UI
        but queued for async download/processing. No inline downloads.
        
        Args:
            conn: Database connection
            source: Source configuration
            events: List of events to store
            documents: List of standalone documents to store
            city_id: City identifier
            city_name: City display name (for AI enrichment)
            mcp_client: Optional MCP client for event deduplication
            entity_id: Optional entity ID from source config
            data_start_date: Optional cutoff date - skip items before this date
        """
        # Filter events and documents by data_start_date if set
        if data_start_date:
            original_event_count = len(events)
            original_doc_count = len(documents)
            
            # Filter events by starts_at (the Event model uses starts_at, not start_time)
            events = [e for e in events if e.starts_at and e.starts_at >= data_start_date]
            
            # Filter standalone documents by meeting_date or published_at
            def doc_after_start(d):
                doc_date = d.meeting_date or d.published_at
                return not doc_date or doc_date >= data_start_date
            
            documents = [d for d in documents if doc_after_start(d)]
            
            # Also filter documents attached to events
            for event in events:
                if event.documents:
                    event.documents = [d for d in event.documents if doc_after_start(d)]
            
            filtered_events = original_event_count - len(events)
            filtered_docs = original_doc_count - len(documents)
            if filtered_events > 0 or filtered_docs > 0:
                logger.info(f"Filtered out {filtered_events} events and {filtered_docs} documents before {data_start_date.strftime('%Y-%m-%d')}")

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
            entity_id=entity_id,
        )

        # Store events
        for event in events:
            try:
                if self.ai_processor and self.ai_processor.enabled:
                    event = await self._enrich_event_with_ai(event, city_name)

                event_id = await self.db_pool.upsert_event(
                    conn, source_id, event, ai_processor=self.ai_processor, mcp_client=mcp_client, entity_id=entity_id, city_id=city_id
                )
                logger.debug(f"Stored event: {event.title} -> {event_id}")

                # Register event documents as discovered (visible immediately)
                for document in event.documents:
                    try:
                        doc_id = await self._register_discovered_document(
                            conn, source_id, document, event_id=event_id, entity_id=entity_id
                        )
                        logger.debug(f"Registered event document: {document.title} -> {doc_id}")
                    except Exception as e:
                        logger.error(f"Failed to register event document '{document.title}': {e}")

            except Exception as e:
                logger.error(f"Failed to store event '{event.title}': {e}")

        # Register standalone documents as discovered
        for document in documents:
            try:
                doc_id = await self._register_discovered_document(conn, source_id, document, entity_id=entity_id)
                logger.debug(f"Registered standalone document: {document.title} -> {doc_id}")
            except Exception as e:
                logger.error(f"Failed to register document '{document.title}': {e}")

        await self.db_pool.update_source_health(conn, source_id, success=True)
        logger.info(f"Completed storing results for {source.name}: {len(events)} events, {len(documents)} documents")

    async def _register_discovered_document(
        self, 
        conn, 
        source_id: int, 
        document: Document, 
        event_id: int = None,
        entity_id: int = None,
    ) -> int:
        """
        Register a document as discovered.
        Creates a placeholder that's immediately visible in the UI.
        Document will be queued for download/processing asynchronously.
        
        Args:
            conn: Database connection
            source_id: Source ID
            document: Document to register
            event_id: Optional associated event ID
            entity_id: Optional entity ID from source config
        """
        # Extract document type
        doc_type = None
        if hasattr(document, 'doc_type') and document.doc_type:
            doc_type = str(document.doc_type.value) if hasattr(document.doc_type, 'value') else str(document.doc_type)
        
        # Extract meeting date
        meeting_date = None
        if hasattr(document, 'meeting_date') and document.meeting_date:
            meeting_date = document.meeting_date
        elif hasattr(document, 'published_at') and document.published_at:
            meeting_date = document.published_at
        
        # Get external ID
        external_id = getattr(document, 'external_id', None) or getattr(document, 'id', None)
        if external_id:
            external_id = str(external_id)
        
        # Get source URL
        source_url = document.original_url or getattr(document, 'file_url', None)
        
        # Determine initial status based on content type
        is_video = doc_type == 'video' or (source_url and ('youtu' in source_url.lower()))
        initial_status = ContentStatus.AI_PENDING.value if is_video else ContentStatus.DISCOVERED.value
        
        # Check if document already exists
        existing = await conn.fetchrow("""
            SELECT id, content_status FROM documents 
            WHERE source_id = $1 AND (
                (external_id IS NOT NULL AND external_id = $2)
                OR (source_url IS NOT NULL AND source_url = $3)
            )
        """, source_id, external_id, source_url)
        
        if existing:
            # Update meeting_date if we have a better one
            if meeting_date and not existing.get('meeting_date'):
                await conn.execute("""
                    UPDATE documents SET meeting_date = $1, updated_at = NOW()
                    WHERE id = $2
                """, meeting_date, existing['id'])
            return existing['id']
        
        # Insert new document as discovered
        doc_id = await conn.fetchval("""
            INSERT INTO documents (
                source_id, external_id, title, document_type, source_url,
                meeting_date, content_status, discovered_at, raw_data, entity_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, $9)
            RETURNING id
        """, source_id, external_id, document.title, doc_type, source_url,
             meeting_date, initial_status, 
             getattr(document, 'raw_data', None), entity_id)
        
        # Link to event if provided
        if event_id and doc_id:
            relationship = doc_type or 'related'
            await conn.execute("""
                INSERT INTO event_documents (event_id, document_id, relationship)
                VALUES ($1, $2, $3)
                ON CONFLICT (event_id, document_id) DO UPDATE SET relationship = $3
            """, event_id, doc_id, relationship)
        
        return doc_id

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
