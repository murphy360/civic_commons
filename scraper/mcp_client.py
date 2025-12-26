"""
Scraper MCP Client

Connects to the unified MCP server to execute write operations for event/document
management. Used by the scraper worker to create/update events without direct
database access.

This enables:
- Event deduplication through MCP server
- Automatic event creation when documents are linked
- Write operation logging through activity_log
- Centralized business logic in MCP layer

Connection:
- TCP to localhost:9999 (internal docker network)
- All calls logged with source="scraper"
- Timeouts at 30 seconds per operation
"""

import asyncio
import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("scraper.mcp_client")


class MCPClient:
    """
    Client for communicating with the unified MCP server.
    
    Provides write-level access to event management tools.
    """
    
    def __init__(self, host: str = "localhost", port: int = 9999):
        """
        Initialize MCP client.
        
        Args:
            host: MCP server hostname (default: localhost for docker internal)
            port: MCP server TCP port (default: 9999)
        """
        self.host = host
        self.port = port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._request_id = 0
    
    async def connect(self) -> bool:
        """
        Connect to MCP server.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=5.0,
            )
            self._connected = True
            logger.info(f"Connected to MCP server at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            self._connected = False
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from MCP server."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
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
            city_id: City context (optional)
            
        Returns:
            Tool result dictionary
        """
        if not self._connected:
            if not await self.connect():
                return {"error": "Not connected to MCP server"}
        
        try:
            # Build MCP request (simplified JSON-RPC style)
            self._request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": args,
                    "source": "scraper",
                    "city_id": city_id,
                },
            }
            
            # Send request
            self._writer.write(json.dumps(request).encode() + b"\n")
            await self._writer.drain()
            
            # Read response with timeout
            response_line = await asyncio.wait_for(
                self._reader.readline(),
                timeout=30.0,
            )
            
            response = json.loads(response_line.decode())
            
            # Check for errors
            if "error" in response:
                logger.error(f"Tool call error: {response['error']}")
                return {"error": response["error"].get("message", "Unknown error")}
            
            return response.get("result", {})
        
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
    host: str = "localhost",
    port: int = 9999,
) -> MCPClient:
    """
    Get or create the global MCP client instance.
    
    Args:
        host: MCP server host
        port: MCP server port
        
    Returns:
        Initialized MCPClient
    """
    global _client
    if _client is None:
        _client = MCPClient(host=host, port=port)
        if not await _client.connect():
            logger.warning("MCP client could not connect - operations will fail")
    return _client


async def close_mcp_client() -> None:
    """Close the global MCP client."""
    global _client
    if _client is not None:
        await _client.disconnect()
        _client = None
