"""
Civic Commons MCP Server

FastMCP server providing LLM-accessible API for community data.

Usage:
    python main.py

Environment Variables:
    DATABASE_URL - PostgreSQL connection string
    MCP_API_KEY - API key for authentication
    MCP_PORT - Server port (default: 8080)
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from config import get_config
from db import Database
from tools import register_tools


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("civic_commons.mcp")


# Global database instance
_db: Database | None = None


async def get_db() -> Database:
    """Get the database instance, initializing if needed."""
    global _db
    if _db is None:
        config = get_config()
        _db = await Database.create(config.database_url)
        logger.info("Database connection pool initialized")
    return _db


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
    
    Initializes database on startup and closes on shutdown.
    """
    logger.info("Starting Civic Commons MCP Server")
    
    # Initialize database
    db = await get_db()
    
    # Register tools with database access
    register_tools(mcp, db)
    
    logger.info("MCP server ready")
    
    try:
        yield
    finally:
        logger.info("Shutting down MCP server")
        await close_db()


def create_app() -> FastMCP:
    """
    Create and configure the FastMCP application.
    
    Returns:
        Configured FastMCP instance
    """
    mcp = FastMCP(
        name="civic-commons",
    )
    
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
        return True
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise


def main() -> None:
    """Main entry point for the MCP server."""
    try:
        config = get_config()
        logger.info(f"Configuration loaded, starting on port {config.port}")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Create and run the MCP server
    mcp = create_app()
    
    # Run with stdio transport (standard for MCP)
    mcp.run()


if __name__ == "__main__":
    main()
