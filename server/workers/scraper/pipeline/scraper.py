"""
Scraper execution and result storage.

Handles running drivers and persisting results to the API server.
Events are sent to /api/events/upsert endpoint for processing.
Documents are registered as "discovered" immediately (visible in UI),
then processed asynchronously through the queue system.
"""

import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.activity_logger_http import ActivityLoggerHTTP as ActivityLogger

from models import Document, Event
from .queue_manager import QueueManager, ContentStatus

logger = logging.getLogger("civic.scraper")


class ScraperExecutor:
    """Executes scraping jobs and sends results to API server."""

    def __init__(self, db_pool, document_downloader=None, 
                 queue_manager: QueueManager = None,
                 activity_logger: Optional["ActivityLogger"] = None,
                 mcp_client=None,
                 api_url: str = "http://localhost:8089"):
        self.db_pool = db_pool
        self.document_downloader = document_downloader
        self.queue_manager = queue_manager
        self.activity = activity_logger
        self.mcp_client = mcp_client
        self.api_url = api_url  # API server base URL

    async def scrape_source(
        self,
        config,
        source,
        get_driver,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
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
            skip_queue_check: If True, skip any queue checks (unused, kept for compatibility)
            
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
        Store scraped results by sending to API server.
        
        Events are sent to /api/events/upsert which handles:
        - MCP analysis for deduplication
        - Database persistence
        - Activity logging
        
        Documents are registered as "discovered" locally.
        
        Args:
            conn: Database connection
            source: Source configuration
            events: List of events to store
            documents: List of standalone documents to store
            city_id: City identifier
            city_name: City display name
            mcp_client: Optional MCP client (deprecated - API handles this)
            entity_id: Optional entity ID from source config
            data_start_date: Optional cutoff date - skip items before this date
        """
        # Filter events and documents by data_start_date if set
        # NOTE: We now send all events to the API; the API/MCP decides on acceptance
        # This allows the system to handle deduplication and date filtering centrally
        if data_start_date:
            original_event_count = len(events)
            original_doc_count = len(documents)
            
            # We log what WOULD be filtered, but don't actually filter
            # This provides visibility without losing data
            old_events = [e for e in events if e.starts_at and e.starts_at < data_start_date]
            old_docs = [d for d in (documents + [doc for e in events for doc in e.documents]) 
                       if (d.meeting_date or d.published_at) and (d.meeting_date or d.published_at) < data_start_date]
            
            if old_events or old_docs:
                logger.info(f"Note: {len(old_events)} events and {len(old_docs)} documents are before {data_start_date.strftime('%Y-%m-%d')} - will still upsert for MCP analysis")

        if not events and not documents:
            return

        # Get or create source
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

        # Send events to API
        for event in events:
            try:
                event_id = await self._upsert_event_via_api(
                    source_id, event, city_id
                )
                logger.debug(f"Stored event via API: {event.title} -> {event_id}")

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

    async def _upsert_event_via_api(
        self,
        source_id: int,
        event: Event,
        city_id: str,
    ) -> int:
        """
        Send event to API server for upsert.
        
        The API server will:
        1. Call MCP to analyze the event
        2. Create or merge in database
        3. Log the decision and action
        
        Args:
            source_id: Source ID
            event: Event to upsert
            city_id: City identifier
            
        Returns:
            Event ID from server
            
        Raises:
            Exception if API call fails
        """
        payload = {
            "source_id": source_id,
            "title": event.title,
            "start_time": event.starts_at.isoformat() if event.starts_at else None,
            "end_time": event.ends_at.isoformat() if event.ends_at else None,
            "location": event.location,
            "description": event.description,
            "category": event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type),
            "is_virtual": event.is_virtual,
            "virtual_url": event.virtual_url,
            "external_id": event.external_id,
            "source_url": event.source_url,
            "city_id": city_id,
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_url}/events/upsert",
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["event_id"]
                else:
                    error = resp.text
                    logger.error(f"API error {resp.status_code}: {error}")
                    raise Exception(f"API returned {resp.status_code}: {error}")
        except httpx.HTTPError as e:
            logger.error(f"API connection error: {e}")
            raise


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

    async def link_documents_to_events(self, conn, documents: list[tuple[int, Document]]) -> None:
        """
        Link standalone documents to events.
        
        Note: AI-based linking is now handled by the cascade service.
        This method is kept for backward compatibility but does nothing.
        """
        pass

