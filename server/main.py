"""
Civic Commons Unified MCP Server

FastMCP server providing LLM-accessible API for community data.
Consolidates all tools (MCP, chat, scraper) with role-based access control.

Usage:
    python main.py                    # Stdio transport (default)
    python main.py --tcp 9999         # TCP transport for docker

Environment Variables:
    DATABASE_URL - PostgreSQL connection string
    MCP_API_KEY - API key for authentication
    MCP_TCP_PORT - TCP server port (default: 9999)
"""

import asyncio
import logging
import sys
import argparse
from contextlib import asynccontextmanager
from typing import AsyncIterator, Any

from mcp.server.fastmcp import FastMCP

from config import get_config
from db import Database
from tool_registry import get_tool_definitions, list_tools
from tool_executor import ToolExecutor
from mcp_event_tools import register_event_tools


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("civic_commons.mcp")


# Global instances
_db: Database | None = None
_executor: ToolExecutor | None = None


async def get_db() -> Database:
    """Get the database instance, initializing if needed."""
    global _db
    if _db is None:
        config = get_config()
        _db = await Database.create(config.database_url)
        logger.info("Database connection pool initialized")
    return _db


async def get_executor() -> ToolExecutor:
    """Get the tool executor instance."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor


async def close_db() -> None:
    """Close the database connection pool."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection pool closed")


@asynccontextmanager
async def lifespan(mcp: FastMCP) -> AsyncIterator[None]:
    """
    Manage server lifecycle.
    
    Initializes database and tools on startup, closes on shutdown.
    """
    logger.info("Starting Civic Commons Unified MCP Server")
    
    # Initialize database and executor
    db = await get_db()
    executor = await get_executor()
    
    # Register all tools with unified registry
    register_unified_tools(mcp, db, executor)
    
    logger.info(f"MCP server ready with {len(list_tools())} tools")
    
    try:
        yield
    finally:
        logger.info("Shutting down MCP server")
        await close_db()


def register_unified_tools(mcp: FastMCP, db: Database, executor: ToolExecutor) -> None:
    """
    Register all tools from unified registry to MCP server.
    
    Args:
        mcp: FastMCP server instance
        db: Database instance
        executor: ToolExecutor instance
    """
    # Get all tools (read-only for external MCP clients)
    tools = get_tool_definitions("read_only")
    
    for tool_name, tool_def in tools.items():
        # Create a tool handler that calls through the executor
        async def tool_handler(**kwargs) -> dict[str, Any]:
            """Generic tool handler that routes through executor."""
            result = await executor.execute_tool(
                name=kwargs.pop("_tool_name_"),
                args=kwargs,
                source="mcp",
                city_id=kwargs.get("city_id"),
                access_level="read_only",
            )
            
            if result.success:
                return result.result
            else:
                return {"error": result.error}
        
        # Bind tool name to the handler
        tool_handler.__name__ = tool_name
        tool_handler.__doc__ = tool_def.description
        
        # Register with MCP server
        mcp.tool(
            name=tool_name,
            description=tool_def.description,
        )(tool_handler)
    
    logger.info(f"Registered {len(tools)} read-only tools")
    
    # Register admin endpoints
    register_admin_tools(mcp, db, executor)
    
    # Register event analysis tools (for scraper integration)
    # Note: activity_logger is None on server side - logging happens on scraper side
    register_event_tools(mcp, db, ai_processor=None, activity_logger=None)


def register_admin_tools(mcp: FastMCP, db: Database, executor: ToolExecutor) -> None:
    """Register administrative/introspection tools."""
    
    @mcp.tool(name="list_available_tools")
    async def list_available_tools() -> dict[str, Any]:
        """
        List all available tools with metadata.
        
        Returns tools accessible in this MCP session.
        """
        tools = list_tools("read_only")
        return {
            "total_count": len(tools),
            "tools": tools,
        }
    
    @mcp.tool(name="get_tool_details")
    async def get_tool_details(tool_name: str) -> dict[str, Any]:
        """
        Get detailed information about a specific tool.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Detailed tool information
        """
        tools = get_tool_definitions()
        if tool_name not in tools:
            return {"error": f"Tool '{tool_name}' not found"}
        
        tool = tools[tool_name]
        return {
            "name": tool_name,
            "description": tool.description,
            "category": tool.category,
            "access_level": tool.access_level,
            "parameters": tool.parameters,
        }
    
    logger.info("Registered admin tools")


def create_app() -> FastMCP:
    """
    Create and configure the unified FastMCP application.
    
    Returns:
        Configured FastMCP instance
    """
    mcp = FastMCP(name="civic-commons-unified")
    
    return mcp


async def health_check() -> bool:
    """
    Perform a health check.
    
    Returns:
        True if healthy, raises exception otherwise
    """
    try:
        db = await get_db()
        # Simple query to verify database connection
        async with db.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        # Check executor
        executor = await get_executor()
        if executor is None:
            raise RuntimeError("Executor not initialized")
        
        return True
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise


def main() -> None:
    """Main entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="Civic Commons MCP Server")
    parser.add_argument("--tcp", type=int, help="Run TCP server on specified port")
    args = parser.parse_args()
    
    try:
        config = get_config()
        logger.info("Configuration loaded")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Initialize database and tools synchronously
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Initialize database and executor
        db = loop.run_until_complete(get_db())
        executor = loop.run_until_complete(get_executor())
        
        # Create the MCP server
        mcp = create_app()
        
        # Register all tools with unified registry
        register_unified_tools(mcp, db, executor)
        
        logger.info(f"MCP server ready with {len(list_tools())} tools")
        
        # Run stdio server (FastMCP handles stdio by default)
        # For TCP, the scraper will connect to this server via TCP bridge if needed
        logger.info("Starting stdio server (listening on stdin/stdout)")
        mcp.run()
    
    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        sys.exit(1)
    finally:
        loop.run_until_complete(close_db())
        loop.close()


async def _async_init_and_run_server(mcp: FastMCP, args) -> None:
    """Initialize and run the MCP server asynchronously."""
    # Run initialization in the lifespan context
    async with lifespan(mcp):
        # After initialization, run the server
        if args.tcp:
            logger.info(f"Starting TCP server on port {args.tcp}")
            mcp.run()
        else:
            logger.info("Starting stdio server")
            mcp.run()


if __name__ == "__main__":
    main()

