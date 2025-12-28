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
    from pipeline.activity_logger_http import ActivityLoggerHTTP as ActivityLogger

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
    # ENTITY OPERATIONS
    # =========================================================================

    async def sync_entities(
        self,
        conn: asyncpg.Connection,
        city_id: str,
        entities: dict,  # dict[str, EntityConfig]
    ) -> dict[str, int]:
        """
        Sync entities from config to database.
        
        Args:
            conn: Database connection
            city_id: City identifier
            entities: Dict of entity_key -> EntityConfig from config
        
        Returns:
            Dict mapping entity_key to database entity ID
        """
        entity_id_map = {}
        
        for entity_key, entity in entities.items():
            # Upsert the entity
            row = await conn.fetchrow(
                """
                INSERT INTO entities (
                    city_id, entity_key, display_name, short_name, domain,
                    entity_type, parent_entity_key, aliases, icon
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (city_id, entity_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    short_name = EXCLUDED.short_name,
                    domain = EXCLUDED.domain,
                    entity_type = EXCLUDED.entity_type,
                    parent_entity_key = EXCLUDED.parent_entity_key,
                    aliases = EXCLUDED.aliases,
                    icon = EXCLUDED.icon,
                    updated_at = NOW()
                RETURNING id
                """,
                city_id,
                entity_key,
                entity.display_name,
                entity.short_name,
                entity.domain,
                entity.type,
                entity.parent,
                entity.aliases if entity.aliases else None,
                entity.icon,
            )
            entity_id_map[entity_key] = row["id"]
        
        # Update parent_entity_id references now that all entities exist
        for entity_key, entity in entities.items():
            if entity.parent and entity.parent in entity_id_map:
                await conn.execute(
                    """
                    UPDATE entities SET parent_entity_id = $1
                    WHERE city_id = $2 AND entity_key = $3
                    """,
                    entity_id_map[entity.parent],
                    city_id,
                    entity_key,
                )
        
        logger.info(f"Synced {len(entity_id_map)} entities for city {city_id}")
        return entity_id_map

    async def sync_color_schemes(
        self,
        conn: asyncpg.Connection,
        city_id: str,
        color_schemes: dict,  # dict[str, ColorSchemeConfig]
    ) -> None:
        """
        Sync color schemes from config to database.
        
        Args:
            conn: Database connection
            city_id: City identifier
            color_schemes: Dict of domain -> ColorSchemeConfig from config
        """
        for domain, scheme in color_schemes.items():
            await conn.execute(
                """
                INSERT INTO color_schemes (
                    city_id, domain, primary_color, light_color, 
                    dark_color, border_color, icon
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (city_id, domain) DO UPDATE SET
                    primary_color = EXCLUDED.primary_color,
                    light_color = EXCLUDED.light_color,
                    dark_color = EXCLUDED.dark_color,
                    border_color = EXCLUDED.border_color,
                    icon = EXCLUDED.icon,
                    updated_at = NOW()
                """,
                city_id,
                domain,
                scheme.primary,
                scheme.light,
                scheme.dark,
                scheme.border,
                scheme.icon,
            )
        
        logger.info(f"Synced {len(color_schemes)} color schemes for city {city_id}")

    async def get_entity_id(
        self,
        conn: asyncpg.Connection,
        city_id: str,
        entity_key: str | None,
    ) -> int | None:
        """
        Get entity database ID from entity key.
        
        Args:
            conn: Database connection
            city_id: City identifier
            entity_key: Entity key from config (e.g., "city_council")
        
        Returns:
            Entity database ID or None if not found
        """
        if not entity_key:
            return None
        
        row = await conn.fetchrow(
            "SELECT id FROM entities WHERE city_id = $1 AND entity_key = $2",
            city_id,
            entity_key,
        )
        return row["id"] if row else None

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
        entity_id: int | None = None,
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
            entity_id: Database ID of the associated entity
        
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
                SET is_enabled = $1, config = $2, city_id = $3, entity_id = $4
                WHERE id = $5
                """,
                is_enabled,
                config_json,
                city_id,
                entity_id,
                row["id"],
            )
            return row["id"]

        # Create new source
        config_json = json.dumps(config) if config else "{}"
        row = await conn.fetchrow(
            """
            INSERT INTO sources (city_id, name, source_type, driver_type, url, config, is_enabled, entity_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            city_id,
            name,
            "public",  # source_type
            driver,
            config.get("base_url", config.get("feed_url", "")),  # url
            config_json,
            is_enabled,
            entity_id,
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
        entity_id: int | None = None,
    ) -> int:
        """
        Create a new canonical event.
        
        Note: This creates the event only. Use add_event_source() to link
        it to sources.
        
        Args:
            conn: Database connection
            event: Event model instance
            entity_id: Optional entity ID for the event
        
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
                entity_id, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)
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
            entity_id,
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
    
    async def add_event_city(
        self,
        conn: asyncpg.Connection,
        event_id: int,
        city_id: str,
        is_primary: bool = True,
    ) -> int:
        """
        Link an event to a city.
        
        Supports multi-city events where the same event may be referenced
        by sources from different cities (e.g., regional meetings).
        
        Args:
            conn: Database connection
            event_id: ID of the event
            city_id: City identifier (e.g., 'twinsburg_oh')
            is_primary: True if this city first discovered this event
        
        Returns:
            event_cities ID
        """
        now = datetime.utcnow()
        
        row = await conn.fetchrow(
            """
            INSERT INTO event_cities (
                event_id, city_id, is_primary, first_seen_at, last_seen_at
            )
            VALUES ($1, $2, $3, $4, $4)
            ON CONFLICT (event_id, city_id) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at
            RETURNING id
            """,
            event_id,
            city_id,
            is_primary,
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

    async def update_event_from_document_metadata(
        self,
        conn: asyncpg.Connection,
        event_id: int,
        metadata: dict,
    ) -> bool:
        """
        Update event with metadata extracted from linked documents.
        
        Only updates fields that are currently missing or have placeholder values.
        This prevents AI-extracted data from overwriting human-entered data.
        
        Args:
            conn: Database connection
            event_id: Event to update
            metadata: Dict with meeting_date, meeting_time, location, meeting_type
            
        Returns:
            True if any fields were updated
        """
        import logging
        logger = logging.getLogger("civic.storage")
        
        # Get current event data
        event = await conn.fetchrow(
            "SELECT start_time, location, category FROM events WHERE id = $1",
            event_id
        )
        
        if not event:
            logger.warning(f"Event {event_id} not found for metadata update")
            return False
        
        updates = {}
        
        # Update time if currently midnight (placeholder) and we have extracted time
        if metadata.get("meeting_time") and metadata.get("meeting_date"):
            current_time = event["start_time"]
            # Check if time is midnight (00:00:00) - a placeholder value
            if current_time and current_time.hour == 0 and current_time.minute == 0:
                try:
                    from datetime import datetime as dt
                    # Parse the extracted date and time
                    date_str = metadata["meeting_date"]
                    time_str = metadata["meeting_time"]
                    new_datetime = dt.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                    
                    # Only update if the dates match (sanity check)
                    if current_time.date() == new_datetime.date():
                        updates["start_time"] = new_datetime
                        logger.info(f"Event {event_id}: updating time from 00:00 to {time_str}")
                    else:
                        logger.debug(
                            f"Event {event_id}: date mismatch - event has {current_time.date()}, "
                            f"metadata has {new_datetime.date()}"
                        )
                except (ValueError, TypeError) as e:
                    logger.warning(f"Event {event_id}: failed to parse time '{metadata.get('meeting_time')}': {e}")
        
        # Update location if currently empty and we have extracted location
        if metadata.get("location") and not event.get("location"):
            updates["location"] = metadata["location"]
            logger.info(f"Event {event_id}: adding location '{metadata['location'][:50]}...'")
        
        # Update category/meeting_type if we have it and current is generic
        if metadata.get("meeting_type") and event.get("category") in (None, "", "meeting", "other"):
            updates["category"] = metadata["meeting_type"]
            logger.info(f"Event {event_id}: updating category to '{metadata['meeting_type']}'")
        
        if updates:
            await self.update_event(conn, event_id, **updates)
            return True
        
        return False

    async def upsert_event(
        self,
        conn: asyncpg.Connection,
        source_id: int,
        event: Event,
        mcp_client: Optional[Any] = None,
        entity_id: int | None = None,
        city_id: str | None = None,
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
            mcp_client: Optional MCP client for centralized decisions
            entity_id: Optional entity ID from the source's config
            city_id: Optional city identifier for event-city association
        
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
                    event_id = await self.create_event(conn, event, entity_id=entity_id)
                    await self.add_event_source(
                        conn, event_id, source_id,
                        external_id=event.external_id,
                        source_url=event.source_url,
                    )
                    # Link event to city (primary since we're creating it)
                    if city_id:
                        await self.add_event_city(conn, event_id, city_id, is_primary=True)
                    logger.info(f"MCP-created event: '{event.title}' -> {event_id}")
                    
                    # Log the successful upsert action
                    if self.activity:
                        await self.activity.log(
                            level="success",
                            category="tool_call",
                            action="upsert_event_created",
                            message=f"✓ Created new event: {event.title} [Date: {event.starts_at.isoformat() if event.starts_at else 'TBD'}, Location: {event.location or 'TBD'}]",
                            entity_type="event",
                            entity_id=event_id,
                            entity_title=event.title,
                            details={
                                "event_id": event_id,
                                "source_id": source_id,
                                "action": "create",
                                "decision": decision,
                            }
                        )
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
                        # Link event to city (not primary since we're merging)
                        if city_id:
                            await self.add_event_city(conn, merge_event_id, city_id, is_primary=False)
                        logger.info(
                            f"MCP-merged event '{event.title}' to {merge_event_id} "
                            f"(confidence: {confidence:.2f})"
                        )
                        
                        # Log the successful upsert action
                        if self.activity:
                            await self.activity.log(
                                level="success",
                                category="tool_call",
                                action="upsert_event_merged",
                                message=f"⟷ Merged into event #{merge_event_id}: {event.title} (confidence: {confidence:.0%}) [Date: {event.starts_at.isoformat() if event.starts_at else 'TBD'}, Location: {event.location or 'TBD'}]",
                                entity_type="event",
                                entity_id=merge_event_id,
                                entity_title=event.title,
                                details={
                                    "event_id": merge_event_id,
                                    "source_id": source_id,
                                    "action": "merge",
                                    "confidence": confidence,
                                    "decision": decision,
                                }
                            )
                        return merge_event_id
            
            # If MCP decision failed or returned error, fall through to local logic
            logger.warning(
                f"MCP decision failed or unavailable: {decision}. "
                f"Falling back to local deduplication."
            )
        
        # Fall back to local deduplication logic
        return await self._upsert_event_local(
            conn, source_id, event, entity_id=entity_id, city_id=city_id
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
                    args={
                        "title": event.title, 
                        "source_id": source_id,
                        "start_time": event.starts_at.isoformat() if event.starts_at else None,
                        "location": event.location,
                    },
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
        entity_id: int | None = None,
        city_id: str | None = None,
    ) -> int:
        """
        Insert or update an event using local deduplication logic.
        
        This is the fallback when MCP is unavailable.
        
        Deduplication strategy:
        1. Check if this source+external_id already exists (exact match)
        2. Find similar events by title/date using trigram similarity
        3. Auto-merge if similarity >= DEDUP_AUTO_MERGE_THRESHOLD (default 0.65)
        4. Create new event if no match found
        
        Args:
            conn: Database connection
            source_id: ID of the source
            event: Event to upsert
            entity_id: Optional entity ID from the source's config
            city_id: Optional city identifier for event-city association
        
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
                # Ensure event-city association exists (not primary since event already existed)
                if city_id:
                    await self.add_event_city(conn, existing["id"], city_id, is_primary=False)
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
                # Link event to city (not primary since we're merging)
                if city_id:
                    await self.add_event_city(conn, match["id"], city_id, is_primary=False)
                logger.info(
                    "Auto-merged event '%s' to existing event %d (similarity: %.2f)",
                    event.title, match["id"], similarity
                )
                return match["id"]
            
            # Uncertain range - defer to MCP or create new
            # (AI-assisted deduplication now handled by MCP server)
            pass
        
        # No match found - create new event
        event_id = await self.create_event(conn, event, entity_id=entity_id)
        
        # Link to this source
        await self.add_event_source(
            conn,
            event_id,
            source_id,
            external_id=event.external_id,
            source_url=event.source_url,
        )
        
        # Link event to city (primary since we're creating it)
        if city_id:
            await self.add_event_city(conn, event_id, city_id, is_primary=True)
        
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


