"""
Civic Commons MCP Server - Database Layer

Provides async database queries for MCP tools.
"""

from datetime import date, datetime
from typing import Any

import asyncpg


class Database:
    """Async database connection pool and query methods."""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    @classmethod
    async def create(cls, database_url: str) -> "Database":
        """Create a new database instance with connection pool."""
        pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        return cls(pool)
    
    async def close(self) -> None:
        """Close the connection pool."""
        await self.pool.close()
    
    # =========================================================================
    # Event Queries
    # =========================================================================
    
    async def get_events(
        self,
        city_id: str,
        start_date: date,
        end_date: date,
        source_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get events within a date range.
        
        Args:
            city_id: The city identifier (e.g., "twinsburg")
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            source_type: Optional filter by source type
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        query = """
            SELECT 
                e.id,
                e.title,
                e.description,
                e.start_time,
                e.end_time,
                e.location,
                e.source_url,
                s.name as source_name,
                s.source_type
            FROM events e
            JOIN sources s ON e.source_id = s.id
            WHERE s.city_id = $1
              AND e.start_time >= $2
              AND e.start_time <= $3
        """
        params: list[Any] = [city_id, start_date, end_date]
        
        if source_type:
            query += " AND s.source_type = $4"
            params.append(source_type)
        
        query += " ORDER BY e.start_time ASC LIMIT $" + str(len(params) + 1)
        params.append(limit)
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    
    # =========================================================================
    # Document Search
    # =========================================================================
    
    async def search_documents(
        self,
        city_id: str,
        query: str,
        source_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Full-text search of documents.
        
        Args:
            city_id: The city identifier
            query: Search query string
            source_type: Optional filter by source type
            limit: Maximum number of results
            
        Returns:
            List of document dictionaries with relevance scores
        """
        sql = """
            SELECT 
                d.id,
                d.title,
                d.document_type,
                d.source_url,
                d.published_date,
                s.name as source_name,
                s.source_type,
                ts_rank(d.search_vector, plainto_tsquery('english', $2)) as rank
            FROM documents d
            JOIN sources s ON d.source_id = s.id
            WHERE s.city_id = $1
              AND d.search_vector @@ plainto_tsquery('english', $2)
        """
        params: list[Any] = [city_id, query]
        
        if source_type:
            sql += " AND s.source_type = $3"
            params.append(source_type)
        
        sql += " ORDER BY rank DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(row) for row in rows]
    
    async def get_document_content(
        self,
        document_id: int,
    ) -> dict[str, Any] | None:
        """
        Get full document content by ID.
        
        Args:
            document_id: The document ID
            
        Returns:
            Document dictionary with full content, or None if not found
        """
        query = """
            SELECT 
                d.id,
                d.title,
                d.document_type,
                d.content_text,
                d.content_markdown,
                d.source_url,
                d.published_date,
                s.name as source_name,
                s.source_type,
                s.city_id
            FROM documents d
            JOIN sources s ON d.source_id = s.id
            WHERE d.id = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, document_id)
            return dict(row) if row else None
    
    # =========================================================================
    # Source Health
    # =========================================================================
    
    async def get_source_health(
        self,
        city_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get health status of all sources for a city.
        
        Args:
            city_id: The city identifier
            
        Returns:
            List of source health dictionaries
        """
        query = """
            SELECT 
                s.id,
                s.name,
                s.source_type,
                s.url,
                s.last_fetched_at,
                s.last_success_at,
                s.last_error,
                s.consecutive_failures,
                s.is_enabled,
                CASE 
                    WHEN s.consecutive_failures >= 3 THEN 'unhealthy'
                    WHEN s.last_error IS NOT NULL THEN 'degraded'
                    WHEN s.last_success_at IS NULL THEN 'unknown'
                    ELSE 'healthy'
                END as health_status
            FROM sources s
            WHERE s.city_id = $1
            ORDER BY s.name
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, city_id)
            return [dict(row) for row in rows]
    
    # =========================================================================
    # City Configuration
    # =========================================================================
    
    async def get_assistant_config(
        self,
        city_id: str,
    ) -> dict[str, Any] | None:
        """
        Get assistant configuration for a city.
        
        Args:
            city_id: The city identifier
            
        Returns:
            Assistant config dictionary or None if not found
        """
        query = """
            SELECT 
                c.id,
                c.city_id,
                c.display_name,
                c.assistant_name,
                c.assistant_persona,
                c.timezone,
                c.metadata
            FROM city_configs c
            WHERE c.city_id = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, city_id)
            return dict(row) if row else None
