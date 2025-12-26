"""
Purpose: Database connection pool and storage operations
Dependencies: asyncpg for PostgreSQL async access
Consumed by: main.py, pipeline
Side effects: Reads/writes to PostgreSQL database
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Any
from uuid import UUID

import asyncpg

from models import Event, Document

if TYPE_CHECKING:
    from pipeline.ai_processor import AIEventProcessor
    from pipeline.activity_logger import ActivityLogger

logger = logging.getLogger("civic.storage")

# Deduplication thresholds (configurable via environment)
# Events with similarity >= AUTO_MERGE_THRESHOLD are automatically merged
# Events with similarity >= AI_REVIEW_THRESHOLD but < AUTO_MERGE_THRESHOLD are sent to AI for review
# Events with similarity < AI_REVIEW_THRESHOLD are considered unique
DEDUP_AUTO_MERGE_THRESHOLD = float(os.getenv("DEDUP_AUTO_MERGE_THRESHOLD", "0.65"))
DEDUP_AI_REVIEW_THRESHOLD = float(os.getenv("DEDUP_AI_REVIEW_THRESHOLD", "0.45"))


class DatabasePool:
    """
    Async database connection pool manager.
    
    Provides connection pooling for PostgreSQL and common
    CRUD operations for events and documents.
    
    Can optionally use MCP client for unified event management,
    falling back to direct DB if MCP is unavailable.
    """

    def __init__(self, pool: asyncpg.Pool, mcp_client=None, activity_logger: Optional["ActivityLogger"] = None):
        self._pool = pool
        self.mcp_client = mcp_client  # Optional MCP client for write operations
        self.activity = activity_logger  # Optional activity logger for tracking operations

    @classmethod
    async def create(cls, database_url: str, mcp_client=None, activity_logger: Optional["ActivityLogger"] = None) -> "DatabasePool":
        """
        Create a new database pool.
        
        Args:
            database_url: PostgreSQL connection string
            mcp_client: Optional MCP client for unified event management
            activity_logger: Optional ActivityLogger for tracking operations
            
        Returns:
            Initialized DatabasePool instance
        """
        pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        logger.info("Database pool created")
        return cls(pool, mcp_client=mcp_client, activity_logger=activity_logger)

    async def close(self) -> None:
        """Close the connection pool."""
        await self._pool.close()
        logger.info("Database pool closed")

    def acquire(self):
        """Acquire a connection from the pool."""
        return self._pool.acquire()

    # =========================================================================
    # CITY OPERATIONS
    # =========================================================================

    async def get_or_create_city(
        self,
        conn: asyncpg.Connection,
        city_id: str,
        display_name: str,
        assistant_name: str = None,
        assistant_persona: str = None,
        timezone: str = None,
    ) -> str:
        """
        Get existing city or create new one from config.
        
        Args:
            conn: Database connection
            city_id: City identifier (e.g., 'twinsburg_oh')
            display_name: Human-readable city name (e.g., 'Twinsburg, Ohio')
            assistant_name: Name of the AI assistant
            assistant_persona: Persona description for the assistant
            timezone: City timezone
        
        Returns:
            City ID (string)
        """
        # Try to find existing
        row = await conn.fetchrow(
            "SELECT city_id FROM cities WHERE city_id = $1",
            city_id,
        )
        
        if row:
            # Update existing city with current config values
            await conn.execute(
                """
                UPDATE cities 
                SET display_name = $2, assistant_name = $3, assistant_persona = $4, timezone = $5, updated_at = NOW()
                WHERE city_id = $1
                """,
                city_id,
                display_name,
                assistant_name,
                assistant_persona,
                timezone,
            )
            return city_id

        # Create new city
        await conn.execute(
            """
            INSERT INTO cities (city_id, display_name, assistant_name, assistant_persona, timezone)
            VALUES ($1, $2, $3, $4, $5)
            """,
            city_id,
            display_name,
            assistant_name,
            assistant_persona,
            timezone,
        )
        logger.info(f"Created city: {city_id} ({display_name})")
        return city_id

    # =========================================================================
    # SOURCE OPERATIONS
    # =========================================================================

    async def get_or_create_source(
        self,
        conn: asyncpg.Connection,
        name: str,
        driver: str,
        config: dict,
        city_id: str,
        is_enabled: bool = True,
        schedule: str = "",
    ) -> int:
        """
        Get existing source or create new one.
        
        Args:
            conn: Database connection
            name: Source name from config
            driver: Driver type (e.g., 'civic_plus', 'rss')
            config: Source configuration parameters
            city_id: City identifier
            is_enabled: Whether the source is enabled for scraping
            schedule: Cron schedule expression
        
        Returns:
            Source ID (integer)
        """
        import json
        
        # Try to find existing
        row = await conn.fetchrow(
            "SELECT id FROM sources WHERE name = $1 AND driver_type = $2",
            name,
            driver,
        )
        
        if row:
            # Update existing source with current config values
            config_json = json.dumps(config) if config else "{}"
            await conn.execute(
                """
                UPDATE sources 
                SET is_enabled = $1, config = $2, city_id = $3
                WHERE id = $4
                """,
                is_enabled,
                config_json,
                city_id,
                row["id"],
            )
            return row["id"]

        # Create new source
        config_json = json.dumps(config) if config else "{}"
        row = await conn.fetchrow(
            """
            INSERT INTO sources (city_id, name, source_type, driver_type, url, config, is_enabled)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            city_id,
            name,
            "public",  # source_type
            driver,
            config.get("base_url", config.get("feed_url", "")),  # url
            config_json,
            is_enabled,
        )
        return row["id"]

    async def update_source_health(
        self,
        conn: asyncpg.Connection,
        source_id: int,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """Update source health tracking after a scrape."""
        import logging
        logger = logging.getLogger("civic.storage")
        
        now = datetime.utcnow()
        logger.info(f"Updating source health for source_id={source_id}, success={success}")
        
        if success:
            result = await conn.execute(
                """
                UPDATE sources SET
                    last_success_at = $1,
                    last_fetched_at = $1,
                    consecutive_failures = 0,
                    last_error = NULL,
                    updated_at = $1
                WHERE id = $2
                """,
                now,
                source_id,
            )
            logger.info(f"Updated source health (success) for source_id={source_id}: {result}")
        else:
            result = await conn.execute(
                """
                UPDATE sources SET
                    last_fetched_at = $1,
                    consecutive_failures = consecutive_failures + 1,
                    last_error = $2,
                    updated_at = $1
                WHERE id = $3
                """,
                now,
                error_message,
                source_id,
            )
            logger.info(f"Updated source health (failure) for source_id={source_id}: {result}")

    # =========================================================================
    # EVENT OPERATIONS
    # =========================================================================

    async def find_similar_events(
        self,
        conn: asyncpg.Connection,
        title: str,
        start_time: datetime,
        hours_window: int = 24,
        limit: int = 5,
    ) -> list[dict]:
        """
        Find events that might be duplicates of a given title/time.
        
        Uses trigram similarity for fuzzy title matching within a time window.
        
        Args:
            title: Event title to match
            start_time: Event start time
            hours_window: Hours before/after to search
            limit: Max results to return
            
        Returns:
            List of potential matches with similarity scores
        """
        from datetime import timedelta
        
        # Calculate time window
        start_window = start_time - timedelta(hours=hours_window)
        end_window = start_time + timedelta(hours=hours_window)
        
        rows = await conn.fetch(
            """
            SELECT 
                id,
                title,
                start_time,
                end_time,
                location,
                category,
                similarity(title, $1) as title_similarity
            FROM events
            WHERE start_time BETWEEN $2 AND $3
              AND similarity(title, $1) > 0.3
            ORDER BY title_similarity DESC, start_time
            LIMIT $4
            """,
            title,
            start_window,
            end_window,
            limit,
        )
        return [dict(row) for row in rows]
    
    async def get_event_by_source_external_id(
        self,
        conn: asyncpg.Connection,
        source_id: int,
        external_id: str,
    ) -> Optional[dict]:
        """
        Find an event by its source-specific external ID.
        
        Uses the event_sources junction table.
        
        Returns:
            Event dict if found, None otherwise
        """
        row = await conn.fetchrow(
            """
            SELECT e.*, es.source_url as es_source_url
            FROM events e
            JOIN event_sources es ON e.id = es.event_id
            WHERE es.source_id = $1 AND es.external_id = $2
            """,
            source_id,
            external_id,
        )
        return dict(row) if row else None
    
    async def create_event(
        self,
        conn: asyncpg.Connection,
        event: Event,
    ) -> int:
        """
        Create a new canonical event.
        
        Note: This creates the event only. Use add_event_source() to link
        it to sources.
        
        Returns:
            Event ID (integer)
        """
        now = datetime.utcnow()
        
        # Handle event_type - could be enum (with .value) or already a string
        if hasattr(event, 'event_type') and event.event_type:
            event_type_str = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)
        else:
            event_type_str = None
        
        row = await conn.fetchrow(
            """
            INSERT INTO events (
                title, description, start_time, end_time, location,
                category, is_cancelled, is_virtual, virtual_url,
                created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)
            RETURNING id
            """,
            event.title,
            event.description,
            event.starts_at,
            event.ends_at,
            event.location,
            event_type_str,
            getattr(event, 'is_cancelled', False),
            getattr(event, 'is_virtual', False),
            getattr(event, 'virtual_url', None),
            now,
        )
        return row["id"]
    
    async def add_event_source(
        self,
        conn: asyncpg.Connection,
        event_id: int,
        source_id: int,
        external_id: Optional[str] = None,
        source_url: Optional[str] = None,
        raw_data: Optional[dict] = None,
    ) -> int:
        """
        Link an event to a source.
        
        Records that this source reports this event, with its source-specific
        external ID and URL.
        
        Returns:
            event_sources ID
        """
        import json
        now = datetime.utcnow()
        
        raw_json = json.dumps(raw_data) if raw_data else None
        
        row = await conn.fetchrow(
            """
            INSERT INTO event_sources (
                event_id, source_id, external_id, source_url, raw_data,
                first_seen_at, last_seen_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $6)
            ON CONFLICT (event_id, source_id) DO UPDATE SET
                external_id = COALESCE(EXCLUDED.external_id, event_sources.external_id),
                source_url = COALESCE(EXCLUDED.source_url, event_sources.source_url),
                raw_data = COALESCE(EXCLUDED.raw_data, event_sources.raw_data),
                last_seen_at = EXCLUDED.last_seen_at
            RETURNING id
            """,
            event_id,
            source_id,
            external_id,
            source_url,
            raw_json,
            now,
        )
        return row["id"]
    
    async def update_event(
        self,
        conn: asyncpg.Connection,
        event_id: int,
        **fields,
    ) -> None:
        """
        Update specific fields on an event.
        
        Args:
            event_id: ID of event to update
            **fields: Field names and values to update
        """
        if not fields:
            return
            
        # Build dynamic UPDATE query
        set_clauses = []
        values = []
        for i, (key, value) in enumerate(fields.items(), 1):
            set_clauses.append(f"{key} = ${i}")
            values.append(value)
        
        values.append(datetime.utcnow())
        set_clauses.append(f"updated_at = ${len(values)}")
        
        values.append(event_id)
        
        query = f"""
            UPDATE events SET {', '.join(set_clauses)}
            WHERE id = ${len(values)}
        """
        
        await conn.execute(query, *values)

    async def upsert_event(
        self,
        conn: asyncpg.Connection,
        source_id: int,
        event: Event,
        ai_processor: Optional["AIEventProcessor"] = None,
        mcp_client: Optional[Any] = None,
    ) -> int:
        """
        Insert or update an event with MCP-powered deduplication (if available).
        
        Decision Path (with MCP):
        1. Call MCP's analyze_event_for_upsert_tool
        2. Implement decision: create new or merge with recommended event_id
        3. If MCP unavailable, fall back to local deduplication
        
        Args:
            conn: Database connection
            source_id: ID of the source
            event: Event to upsert
            ai_processor: Optional AI processor for local fallback
            mcp_client: Optional MCP client for centralized decisions
        
        Returns:
            Event ID (integer)
        """
        # Try MCP-based decision first (if available)
        if mcp_client:
            decision = await self._get_mcp_event_decision(
                mcp_client, source_id, event
            )
            
            if decision and "error" not in decision:
                action = decision.get("action")
                
                if action == "create":
                    # Create new event
                    event_id = await self.create_event(conn, event)
                    await self.add_event_source(
                        conn, event_id, source_id,
                        external_id=event.external_id,
                        source_url=event.source_url,
                    )
                    logger.info(f"MCP-created event: '{event.title}' -> {event_id}")
                    return event_id
                
                elif action == "merge":
                    merge_event_id = decision.get("event_id")
                    confidence = decision.get("confidence", 0)
                    if merge_event_id:
                        await self.add_event_source(
                            conn, merge_event_id, source_id,
                            external_id=event.external_id,
                            source_url=event.source_url,
                        )
                        logger.info(
                            f"MCP-merged event '{event.title}' to {merge_event_id} "
                            f"(confidence: {confidence:.2f})"
                        )
                        return merge_event_id
            
            # If MCP decision failed or returned error, fall through to local logic
            logger.warning(
                f"MCP decision failed or unavailable: {decision}. "
                f"Falling back to local deduplication."
            )
        
        # Fall back to local deduplication logic
        return await self._upsert_event_local(
            conn, source_id, event, ai_processor
        )
    
    async def _get_mcp_event_decision(
        self, mcp_client: Any, source_id: int, event: Event
    ) -> dict[str, Any]:
        """
        Get event upsert decision from MCP server.
        
        Args:
            mcp_client: MCP client instance
            source_id: Event source ID
            event: Event to analyze
            
        Returns:
            Decision dict: {action, event_id, confidence, reasoning, error}
        """
        start_time = time.time()
        try:
            # Convert event_type enum to string if needed
            category = event.event_type.value if hasattr(event.event_type, 'value') else str(event.event_type)
            
            args = {
                "source_id": source_id,
                "title": event.title,
                "start_time": event.starts_at.isoformat(),
                "end_time": event.ends_at.isoformat() if event.ends_at else None,
                "location": event.location,
                "description": event.description,
                "category": category,
                "is_virtual": event.is_virtual,
                "virtual_url": event.virtual_url,
                "external_id": event.external_id,
                "source_url": event.source_url,
            }
            
            decision = await mcp_client.call_tool(
                "analyze_event_for_upsert_tool",
                args=args,
            )
            
            # Log the tool call
            if self.activity:
                duration_ms = (time.time() - start_time) * 1000
                await self.activity.log_tool_completed(
                    tool_name="analyze_event_for_upsert",
                    args={"title": event.title, "source_id": source_id},
                    result=decision,
                    execution_time_ms=duration_ms,
                    source="mcp",
                )
            
            return decision
        except Exception as e:
            logger.error(f"MCP call failed: {e}")
            
            # Log the failure
            if self.activity:
                duration_ms = (time.time() - start_time) * 1000
                await self.activity.log_tool_failed(
                    tool_name="analyze_event_for_upsert",
                    error=str(e),
                    execution_time_ms=duration_ms,
                    source="mcp",
                )
            
            return {"error": str(e)}
    
    async def _upsert_event_local(
        self,
        conn: asyncpg.Connection,
        source_id: int,
        event: Event,
        ai_processor: Optional["AIEventProcessor"] = None,
    ) -> int:
        """
        Insert or update an event using local deduplication logic.
        
        This is the fallback when MCP is unavailable.
        
        Deduplication strategy:
        1. Check if this source+external_id already exists (exact match)
        2. Find similar events by title/date using trigram similarity
        3. Auto-merge if similarity >= DEDUP_AUTO_MERGE_THRESHOLD (default 0.65)
        4. Use AI to verify if similarity is in uncertain range (0.45-0.65)
        5. Create new event if no match found
        
        Args:
            conn: Database connection
            source_id: ID of the source
            event: Event to upsert
            ai_processor: Optional AI processor for uncertain deduplication
        
        Returns:
            Event ID (integer)
        """
        # First, check if we already have this event from this source
        if event.external_id:
            existing = await self.get_event_by_source_external_id(
                conn, source_id, event.external_id
            )
            if existing:
                # Update the existing event
                await self.update_event(
                    conn,
                    existing["id"],
                    title=event.title,
                    description=event.description,
                    start_time=event.starts_at,
                    end_time=event.ends_at,
                    location=event.location,
                )
                return existing["id"]
        
        # Check for similar events by title/date (basic deduplication)
        similar = await self.find_similar_events(
            conn, event.title, event.starts_at, hours_window=4
        )
        
        # Process matches by similarity score
        for match in similar:
            similarity = match["title_similarity"]
            
            # High confidence match - auto-merge
            if similarity >= DEDUP_AUTO_MERGE_THRESHOLD:
                await self.add_event_source(
                    conn,
                    match["id"],
                    source_id,
                    external_id=event.external_id,
                    source_url=event.source_url,
                )
                logger.info(
                    "Auto-merged event '%s' to existing event %d (similarity: %.2f)",
                    event.title, match["id"], similarity
                )
                return match["id"]
            
            # Uncertain range - use AI if available
            elif similarity >= DEDUP_AI_REVIEW_THRESHOLD and ai_processor and ai_processor.enabled:
                # Build Event objects for AI comparison
                existing_event = Event(
                    title=match["title"],
                    starts_at=match["start_time"],
                    ends_at=match.get("end_time"),
                    location=match.get("location"),
                )
                
                # Ask AI if these are duplicates
                ai_match = await ai_processor.detect_duplicates(event, [existing_event])
                
                if ai_match:
                    await self.add_event_source(
                        conn,
                        match["id"],
                        source_id,
                        external_id=event.external_id,
                        source_url=event.source_url,
                    )
                    logger.info(
                        "AI-verified merge: '%s' to existing event %d (similarity: %.2f)",
                        event.title, match["id"], similarity
                    )
                    return match["id"]
                else:
                    logger.debug(
                        "AI rejected merge: '%s' vs '%s' (similarity: %.2f)",
                        event.title, match["title"], similarity
                    )
        
        # No match found - create new event
        event_id = await self.create_event(conn, event)
        
        # Link to this source
        await self.add_event_source(
            conn,
            event_id,
            source_id,
            external_id=event.external_id,
            source_url=event.source_url,
        )
        
        return event_id
    
    async def get_event_with_sources(
        self,
        conn: asyncpg.Connection,
        event_id: int,
    ) -> Optional[dict]:
        """
        Get an event with all its linked sources.
        
        Returns:
            Event dict with 'sources' list, or None if not found
        """
        event = await conn.fetchrow(
            "SELECT * FROM events WHERE id = $1",
            event_id,
        )
        
        if not event:
            return None
        
        sources = await conn.fetch(
            """
            SELECT es.*, s.name as source_name, s.driver_type
            FROM event_sources es
            JOIN sources s ON es.source_id = s.id
            WHERE es.event_id = $1
            """,
            event_id,
        )
        
        result = dict(event)
        result["sources"] = [dict(s) for s in sources]
        return result

    # =========================================================================
    # DOCUMENT OPERATIONS
    # =========================================================================

    async def upsert_document(
        self,
        conn: asyncpg.Connection,
        source_id: int,
        document: Document,
        event_id: Optional[int] = None,
    ) -> int:
        """
        Insert or update a document.
        
        Deduplication is based on file_hash if available,
        otherwise source_url.
        
        Returns:
            Document ID (integer)
        """
        now = datetime.utcnow()

        # Try to find existing by hash or URL
        if document.content_hash:
            existing = await conn.fetchrow(
                "SELECT id FROM documents WHERE file_hash = $1",
                document.content_hash,
            )
        else:
            existing = await conn.fetchrow(
                "SELECT id FROM documents WHERE source_url = $1",
                document.original_url,
            )

        if existing:
            # Update existing
            await conn.execute(
                """
                UPDATE documents SET
                    title = $1,
                    document_type = $2,
                    content_markdown = $3,
                    file_hash = $4,
                    local_path = COALESCE($5, local_path),
                    file_size_bytes = COALESCE($6, file_size_bytes),
                    mime_type = COALESCE($7, mime_type),
                    updated_at = $8
                WHERE id = $9
                """,
                document.title,
                document.doc_type,
                document.content_markdown,
                document.content_hash,
                document.file_path,
                document.file_size_bytes,
                document.mime_type,
                now,
                existing["id"],
            )
            doc_id = existing["id"]
        else:
            # Insert new
            row = await conn.fetchrow(
                """
                INSERT INTO documents (
                    source_id, title, document_type, source_url,
                    file_url, content_markdown, file_hash, 
                    local_path, file_size_bytes, mime_type,
                    published_date, meeting_date, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $13)
                RETURNING id
                """,
                source_id,
                document.title,
                document.doc_type,
                document.original_url,
                document.original_url,  # file_url same as source_url for now
                document.content_markdown,
                document.content_hash,
                document.file_path,
                document.file_size_bytes,
                document.mime_type,
                document.published_at,  # When document was published/uploaded
                document.meeting_date,  # When the meeting occurred (for linking)
                now,
            )
            doc_id = row["id"]
        
        # Link document to event if event_id provided
        if event_id:
            await self.link_document_to_event(conn, doc_id, event_id, document)
        
        return doc_id
    
    async def link_document_to_event(
        self,
        conn: asyncpg.Connection,
        document_id: int,
        event_id: int,
        document: Document = None,
        confidence: float = None,
    ) -> None:
        """
        Create a link between a document and an event.
        
        Determines the relationship type based on document type.
        Also clears the event's AI summary so it will be regenerated
        with the new document included.
        """
        # Determine relationship type from document type
        relationship = "attachment"  # default
        if document and document.doc_type:
            doc_type_str = str(document.doc_type).lower()
            if "agenda" in doc_type_str:
                relationship = "agenda"
            elif "minutes" in doc_type_str:
                relationship = "minutes"
            elif "packet" in doc_type_str:
                relationship = "packet"
            elif "video" in doc_type_str or "recording" in doc_type_str:
                relationship = "video"
        
        # Insert link if not exists
        await conn.execute(
            """
            INSERT INTO event_documents (event_id, document_id, relationship)
            VALUES ($1, $2, $3)
            ON CONFLICT (event_id, document_id) DO UPDATE SET relationship = $3
            """,
            event_id,
            document_id,
            relationship,
        )
        
        # Clear the event's AI summary so it gets regenerated with new document
        await conn.execute(
            """
            UPDATE events SET ai_summary = NULL WHERE id = $1
            """,
            event_id,
        )

    async def update_document_local_path(
        self,
        conn: asyncpg.Connection,
        document_id: int,
        local_path: str,
        file_size_bytes: Optional[int] = None,
        mime_type: Optional[str] = None,
        file_hash: Optional[str] = None,
    ) -> None:
        """
        Update a document's local storage path after download.
        
        Args:
            document_id: Database ID of the document
            local_path: Relative path to the downloaded file
            file_size_bytes: Size of the downloaded file
            mime_type: MIME type of the file
            file_hash: SHA-256 hash of the file content
        """
        await conn.execute(
            """
            UPDATE documents SET
                local_path = $1,
                file_size_bytes = COALESCE($2, file_size_bytes),
                mime_type = COALESCE($3, mime_type),
                file_hash = COALESCE($4, file_hash),
                updated_at = $5
            WHERE id = $6
            """,
            local_path,
            file_size_bytes,
            mime_type,
            file_hash,
            datetime.utcnow(),
            document_id,
        )

    async def update_document_ai_summary(
        self,
        conn: asyncpg.Connection,
        document_id: int,
        ai_summary: str,
        model_used: Optional[str] = None,
    ) -> None:
        """
        Update a document's AI-generated summary.
        
        Args:
            document_id: Database ID of the document
            ai_summary: AI-generated summary text
            model_used: Name of the AI model used (e.g., 'gemini-2.0-flash')
        """
        await conn.execute(
            """
            UPDATE documents SET
                ai_summary = $1,
                ai_summary_updated_at = $2,
                ai_model_used = $3,
                content_status = 'completed',
                ai_completed_at = $2,
                updated_at = $2
            WHERE id = $4
            """,
            ai_summary,
            datetime.utcnow(),
            model_used,
            document_id,
        )

