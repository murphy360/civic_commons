"""
Scraper MCP Client

Connects to the unified MCP server via SSE (Server-Sent Events) HTTP transport.
Used by the scraper worker to execute tools and manage events without direct database access.

This enables:
- Event deduplication through MCP server
- Automatic event creation when documents are linked
- Write operation logging through activity_log
- Centralized business logic in MCP layer

Connection:
- HTTP to localhost:8000 (internal docker network)
- Uses SSE for streaming responses
- All calls logged with source="scraper"
- Timeouts at 30 seconds per operation
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("scraper.mcp_client")


class MCPClient:
    """
    Client for communicating with the unified MCP server via SSE.
    
    Provides tool execution through HTTP/SSE transport.
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize MCP client.
        
        Args:
            base_url: MCP server base URL (default: localhost:8000)
        """
        self.base_url = base_url
        self._http_client: Optional[httpx.AsyncClient] = None
        self._connection_id: Optional[str] = None
        self._connected = False
    
    async def connect(self) -> bool:
        """
        Connect to MCP server and establish SSE connection.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            
            # Create a new connection
            response = await self._http_client.post(f"{self.base_url}/connect")
            response.raise_for_status()
            
            data = response.json()
            self._connection_id = data["connection_id"]
            self._connected = True
            
            logger.info(f"Connected to MCP server at {self.base_url} (connection: {self._connection_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            self._connected = False
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from MCP server."""
        if self._connection_id and self._http_client:
            try:
                await self._http_client.delete(f"{self.base_url}/disconnect/{self._connection_id}")
            except Exception as e:
                logger.warning(f"Error disconnecting: {e}")
            finally:
                await self._http_client.aclose()
                self._http_client = None
                self._connected = False
                logger.info("Disconnected from MCP server")
    
    async def call_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        city_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Call a tool through the MCP server.
        
        Args:
            tool_name: Name of tool to call
            args: Tool arguments
            city_id: City context (optional, passed to args)
            
        Returns:
            Tool result dictionary
        """
        if not self._connected or not self._connection_id:
            if not await self.connect():
                return {"error": "Not connected to MCP server"}
        
        try:
            # Make tool call
            url = f"{self.base_url}/call/{self._connection_id}/{tool_name}"
            response = await self._http_client.post(url, json=args)
            response.raise_for_status()
            
            return response.json()
        
        except asyncio.TimeoutError:
            error_msg = f"Tool call '{tool_name}' timed out after 30 seconds"
            logger.error(error_msg)
            return {"error": error_msg}
        
        except Exception as e:
            error_msg = f"Tool call failed: {str(e)}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    # =========================================================================
    # Convenience methods for common operations
    # =========================================================================
    
    async def create_event(
        self,
        city_id: str,
        title: str,
        start_time: str,
        end_time: Optional[str] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        source_id: Optional[int] = None,
        external_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Create a new event.
        
        Args:
            city_id: City identifier
            title: Event title
            start_time: Start time (ISO format)
            end_time: End time (ISO format)
            location: Event location
            description: Event description
            category: Event category
            source_id: Source data source ID
            external_id: External ID from source
            
        Returns:
            Created event details
        """
        return await self.call_tool(
            "create_event",
            {
                "city_id": city_id,
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "description": description,
                "category": category,
                "source_id": source_id,
                "external_id": external_id,
            },
            city_id=city_id,
        )
    
    async def update_event(
        self,
        event_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        ai_summary: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Update an existing event.
        
        Args:
            event_id: Event ID to update
            title: New title
            description: New description
            location: New location
            ai_summary: AI-generated summary
            
        Returns:
            Updated event details
        """
        return await self.call_tool(
            "update_event",
            {
                "event_id": event_id,
                "title": title,
                "description": description,
                "location": location,
                "ai_summary": ai_summary,
            },
        )
    
    async def add_source_to_event(
        self,
        event_id: int,
        source_id: int,
        external_id: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Link a source to an event (deduplication).
        
        Args:
            event_id: Event ID
            source_id: Source ID
            external_id: External ID from source
            source_url: Source URL
            
        Returns:
            Link result
        """
        return await self.call_tool(
            "add_source_to_event",
            {
                "event_id": event_id,
                "source_id": source_id,
                "external_id": external_id,
                "source_url": source_url,
            },
        )
    
    async def link_document_to_event(
        self,
        event_id: int,
        document_id: int,
        relationship: str = "related",
    ) -> dict[str, Any]:
        """
        Associate a document with an event.
        
        Args:
            event_id: Event ID
            document_id: Document ID
            relationship: Type of relationship (agenda, minutes, summary, etc.)
            
        Returns:
            Link result
        """
        return await self.call_tool(
            "link_document_to_event",
            {
                "event_id": event_id,
                "document_id": document_id,
                "relationship": relationship,
            },
        )
    
    async def enrich_event_data(
        self,
        event_id: int,
        ai_summary: Optional[str] = None,
        key_topics: Optional[list[str]] = None,
        sentiment: Optional[str] = None,
        importance_score: Optional[float] = None,
    ) -> dict[str, Any]:
        """
        Add AI-generated metadata to an event.
        
        Args:
            event_id: Event ID
            ai_summary: AI-generated summary
            key_topics: List of key topics discussed
            sentiment: Overall sentiment (positive, neutral, negative)
            importance_score: Importance score (0.0-1.0)
            
        Returns:
            Enrichment result
        """
        return await self.call_tool(
            "enrich_event_data",
            {
                "event_id": event_id,
                "ai_summary": ai_summary,
                "key_topics": key_topics,
                "sentiment": sentiment,
                "importance_score": importance_score,
            },
        )
    
    async def find_duplicate_events(
        self,
        city_id: str,
        event_id: int,
        similarity_threshold: float = 0.8,
    ) -> dict[str, Any]:
        """
        Find duplicate events by similarity.
        
        Args:
            city_id: City identifier
            event_id: Event to match against
            similarity_threshold: Threshold for duplicate detection (0.0-1.0)
            
        Returns:
            List of similar events
        """
        return await self.call_tool(
            "find_duplicate_events",
            {
                "city_id": city_id,
                "event_id": event_id,
                "similarity_threshold": similarity_threshold,
            },
            city_id=city_id,
        )


# Global client instance
_client: Optional[MCPClient] = None


async def get_mcp_client(
    base_url: str = "http://localhost:8000",
) -> MCPClient:
    """
    Get or create the global MCP client instance.
    
    Args:
        base_url: MCP server base URL (default: http://localhost:8000)
        
    Returns:
        Initialized MCPClient
    """
    global _client
    if _client is None:
        _client = MCPClient(base_url=base_url)
        if not await _client.connect():
            logger.warning("MCP client could not connect - operations will fail")
    return _client


async def close_mcp_client() -> None:
    """Close the global MCP client."""
    global _client
    if _client is not None:
        await _client.disconnect()
        _client = None


