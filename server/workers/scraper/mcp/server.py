"""
MCP Server for Civic Commons Event Management

This server provides tools for an AI to intelligently manage events:
- Query existing events by date/title/similarity
- Create new events
- Add sources to existing events (deduplication)
- Update event details
- Track and link legislation mentions
- Monitor document analysis pipeline

Refactored to use modular handlers for maintainability.
"""

import asyncio
import json
import logging
import os
from typing import Any

import asyncpg
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from .tools import get_tool_definitions
from . import event_handlers
from . import document_handlers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("civic_mcp")

# Database connection
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://commons:password@localhost:5432/civic_commons"
)

app = Server("civic-events")

# Global pool reference for cleanup
_pool = None


async def get_db_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def close_db_pool():
    """Close the database connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# =============================================================================
# Tool Registration
# =============================================================================

@app.list_tools()
async def list_tools():
    """List available tools for event management."""
    return get_tool_definitions()


# =============================================================================
# Tool Dispatch
# =============================================================================

# Map tool names to handler functions
TOOL_HANDLERS = {
    # Event operations
    "search_events": event_handlers.search_events,
    "find_similar_events": event_handlers.find_similar_events,
    "get_event_details": event_handlers.get_event_details,
    "create_event": event_handlers.create_event,
    "add_source_to_event": event_handlers.add_source_to_event,
    "update_event": event_handlers.update_event,
    "process_event_batch": event_handlers.process_event_batch,
    # Legislation operations
    "link_legislation": document_handlers.link_legislation,
    "find_legislation_mentions": document_handlers.find_legislation_mentions,
    # Document operations
    "reanalyze_documents": document_handlers.reanalyze_documents,
    "get_document_analysis_status": document_handlers.get_document_analysis_status,
}


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls by dispatching to appropriate handler."""
    pool = await get_db_pool()
    
    try:
        handler = TOOL_HANDLERS.get(name)
        if handler:
            result = await handler(pool, arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]
    
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


# =============================================================================
# Server Entry Point
# =============================================================================

async def main():
    """Run the MCP server."""
    logger.info("Starting Civic Commons MCP server")
    
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())

