"""
Purpose: Database connection pool and storage operations
Dependencies: asyncpg for PostgreSQL async access
Consumed by: main.py, pipeline
Side effects: Reads/writes to PostgreSQL database
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

import asyncpg

from models import Event, Document

logger = logging.getLogger("civic.storage")


class DatabasePool:
    """
    Async database connection pool manager.
    
    Provides connection pooling for PostgreSQL and common
    CRUD operations for events and documents.
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def create(cls, database_url: str) -> "DatabasePool":
        """
        Create a new database pool.
        
        Args:
            database_url: PostgreSQL connection string
            
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
        return cls(pool)

    async def close(self) -> None:
        """Close the connection pool."""
        await self._pool.close()
        logger.info("Database pool closed")

    def acquire(self):
        """Acquire a connection from the pool."""
        return self._pool.acquire()

    # =========================================================================
    # SOURCE OPERATIONS
    # =========================================================================

    async def get_or_create_source(
        self,
        conn: asyncpg.Connection,
        name: str,
        driver: str,
        config: dict,
    ) -> UUID:
        """
        Get existing source or create new one.
        
        Returns:
            Source UUID
        """
        # Try to find existing
        row = await conn.fetchrow(
            "SELECT id FROM sources WHERE name = $1 AND driver = $2",
            name,
            driver,
        )
        
        if row:
            return row["id"]

        # Create new
        row = await conn.fetchrow(
            """
            INSERT INTO sources (name, driver, config)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            name,
            driver,
            config,
        )
        return row["id"]

    async def update_source_health(
        self,
        conn: asyncpg.Connection,
        source_id: UUID,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """Update source health tracking after a scrape."""
        now = datetime.utcnow()
        
        if success:
            await conn.execute(
                """
                UPDATE sources SET
                    last_success_at = $1,
                    consecutive_failures = 0,
                    last_error_message = NULL,
                    data_as_of = $1,
                    updated_at = $1
                WHERE id = $2
                """,
                now,
                source_id,
            )
        else:
            await conn.execute(
                """
                UPDATE sources SET
                    last_failure_at = $1,
                    consecutive_failures = consecutive_failures + 1,
                    last_error_message = $2,
                    updated_at = $1
                WHERE id = $3
                """,
                now,
                error_message,
                source_id,
            )

    # =========================================================================
    # EVENT OPERATIONS
    # =========================================================================

    async def upsert_event(
        self,
        conn: asyncpg.Connection,
        source_id: UUID,
        event: Event,
    ) -> UUID:
        """
        Insert or update an event.
        
        Deduplication is based on source_id + external_id (if present)
        or source_id + title + starts_at.
        
        Returns:
            Event UUID
        """
        now = datetime.utcnow()

        if event.external_id:
            # Try to find by external ID
            existing = await conn.fetchrow(
                """
                SELECT id FROM events
                WHERE source_id = $1 AND external_id = $2
                """,
                source_id,
                event.external_id,
            )
        else:
            # Try to find by title + date
            existing = await conn.fetchrow(
                """
                SELECT id FROM events
                WHERE source_id = $1 AND title = $2 AND starts_at = $3
                """,
                source_id,
                event.title,
                event.starts_at,
            )

        if existing:
            # Update existing
            await conn.execute(
                """
                UPDATE events SET
                    title = $1,
                    description = $2,
                    starts_at = $3,
                    ends_at = $4,
                    location = $5,
                    url = $6,
                    updated_at = $7
                WHERE id = $8
                """,
                event.title,
                event.description,
                event.starts_at,
                event.ends_at,
                event.location,
                event.source_url,
                now,
                existing["id"],
            )
            return existing["id"]
        else:
            # Insert new
            row = await conn.fetchrow(
                """
                INSERT INTO events (
                    source_id, title, description, starts_at, ends_at,
                    location, url, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
                RETURNING id
                """,
                source_id,
                event.title,
                event.description,
                event.starts_at,
                event.ends_at,
                event.location,
                event.source_url,
                now,
            )
            return row["id"]

    # =========================================================================
    # DOCUMENT OPERATIONS
    # =========================================================================

    async def upsert_document(
        self,
        conn: asyncpg.Connection,
        source_id: UUID,
        document: Document,
        event_id: Optional[UUID] = None,
    ) -> UUID:
        """
        Insert or update a document.
        
        Deduplication is based on content_hash if available,
        otherwise original_url.
        
        Returns:
            Document UUID
        """
        now = datetime.utcnow()

        # Try to find existing by hash or URL
        if document.content_hash:
            existing = await conn.fetchrow(
                "SELECT id FROM documents WHERE content_hash = $1",
                document.content_hash,
            )
        else:
            existing = await conn.fetchrow(
                "SELECT id FROM documents WHERE original_url = $1",
                document.original_url,
            )

        if existing:
            # Update existing
            await conn.execute(
                """
                UPDATE documents SET
                    title = $1,
                    doc_type = $2,
                    file_path = $3,
                    content_markdown = $4,
                    content_hash = $5,
                    updated_at = $6
                WHERE id = $7
                """,
                document.title,
                document.doc_type,
                document.file_path,
                document.content_markdown,
                document.content_hash,
                now,
                existing["id"],
            )
            return existing["id"]
        else:
            # Insert new
            row = await conn.fetchrow(
                """
                INSERT INTO documents (
                    source_id, event_id, title, doc_type, original_url,
                    file_path, content_markdown, content_hash, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                source_id,
                event_id,
                document.title,
                document.doc_type,
                document.original_url,
                document.file_path,
                document.content_markdown,
                document.content_hash,
                now,
            )
            return row["id"]
