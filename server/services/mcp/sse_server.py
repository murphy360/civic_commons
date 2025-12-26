"""
SSE-based MCP Server Transport

Implements Server-Sent Events transport for MCP, allowing browsers and 
remote clients to connect via HTTP instead of stdio. Works with SSE client.

Usage:
    uvicorn sse_server:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..shared.db import Database
from .tool_executor import ToolExecutor
from .tool_registry import get_tool_definitions, list_tools
from ..shared.config import get_config
from .event_tools import analyze_event_for_upsert
from .cascade_tools import trigger_cascade_for_document


logger = logging.getLogger("civic_commons.sse_mcp")

# Global instances
_db: Optional[Database] = None
_executor: Optional[ToolExecutor] = None
_ai_processor: Optional[object] = None
_doc_summarizer: Optional[object] = None
_summary_generator: Optional[object] = None

# Active SSE connections
_connections: dict[str, "SSEConnection"] = {}


class SSEConnection:
    """Manages an SSE connection for MCP communication."""

    def __init__(self, connection_id: str):
        self.connection_id = connection_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.created_at = asyncio.get_event_loop().time()

    async def send_message(self, event: str, data: dict) -> None:
        """Queue a message to send to the client."""
        await self.queue.put({"event": event, "data": data})

    async def stream(self) -> AsyncGenerator[str, None]:
        """Stream SSE messages to the client."""
        try:
            while True:
                # Add timeout to allow graceful shutdown
                try:
                    message = await asyncio.wait_for(self.queue.get(), timeout=30.0)
                    event_type = message.get("event", "message")
                    data = json.dumps(message.get("data", {}))
                    yield f"event: {event_type}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield f"event: keepalive\ndata: {{}}\n\n"
        except asyncio.CancelledError:
            logger.info(f"SSE connection {self.connection_id} closed")
        except Exception as e:
            logger.error(f"Error in SSE stream: {e}")


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


async def get_ai_processor() -> Optional[object]:
    """Get or initialize the AI processor (lazily loaded from scraper)."""
    global _ai_processor
    if _ai_processor is None:
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
        if not gemini_key:
            logger.debug("AI processor disabled (no GEMINI_API_KEY)")
            return None
            
        try:
            # Lazy import from scraper only when needed
            import sys
            from pathlib import Path
            scraper_path = str(Path(__file__).parent.parent.parent.parent / "scraper")
            if scraper_path not in sys.path:
                sys.path.insert(0, scraper_path)
                
            from pipeline.ai_processor import AIEventProcessor
            _ai_processor = AIEventProcessor(api_key=gemini_key)
            logger.info("AI processor initialized")
        except (ImportError, Exception) as e:
            logger.warning(f"Could not initialize AI processor: {e}")
    return _ai_processor


async def get_doc_summarizer() -> Optional[object]:
    """Get or initialize the document summarizer (lazily loaded from scraper)."""
    global _doc_summarizer
    if _doc_summarizer is None:
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
        if not gemini_key:
            return None
            
        try:
            # Lazy import from scraper only when needed
            import sys
            from pathlib import Path
            scraper_path = str(Path(__file__).parent.parent.parent.parent / "scraper")
            if scraper_path not in sys.path:
                sys.path.insert(0, scraper_path)
                
            from pipeline.ai import DocumentSummarizer, GeminiClient
            gemini_client = GeminiClient(api_key=gemini_key)
            _doc_summarizer = DocumentSummarizer(gemini_client)
            logger.info("Document summarizer initialized")
        except (ImportError, Exception) as e:
            logger.warning(f"Could not initialize document summarizer: {e}")
    return _doc_summarizer


async def get_summary_generator() -> Optional[object]:
    """Get or initialize the summary generator (lazily loaded from scraper)."""
    global _summary_generator
    if _summary_generator is None:
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
        if not gemini_key:
            return None
            
        try:
            # Lazy import from scraper only when needed
            import sys
            from pathlib import Path
            scraper_path = str(Path(__file__).parent.parent.parent.parent / "scraper")
            if scraper_path not in sys.path:
                sys.path.insert(0, scraper_path)
                
            from pipeline.ai.summary import SummaryGenerator
            from pipeline.ai import GeminiClient
            gemini_client = GeminiClient(api_key=gemini_key)
            _summary_generator = SummaryGenerator(gemini_client)
            logger.info("Summary generator initialized")
        except (ImportError, Exception) as e:
            logger.warning(f"Could not initialize summary generator: {e}")
    return _summary_generator


async def close_db() -> None:
    """Close the database connection pool."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection pool closed")


def register_unified_tools(app: FastAPI, db: Database, executor: ToolExecutor) -> None:
    """Register all tools from unified registry to FastAPI."""
    # Get all tools
    tools = get_tool_definitions("read_only")
    logger.info(f"Registered {len(tools)} read-only tools")
    
    # Note: register_event_tools is designed for MCP/FastMCP decorator syntax
    # For HTTP/SSE, tools are called via POST /call/{connection_id}/{tool_name}
    # which routes through the tool_executor


# Create FastAPI app
app = FastAPI(title="Civic Commons MCP Server", description="MCP server via SSE transport")


@app.on_event("startup")
async def startup_event():
    """Initialize database and tools on startup."""
    logger.info("Starting Civic Commons MCP SSE Server")
    try:
        config = get_config()
        logger.info("Configuration loaded")
        db = await get_db()
        executor = await get_executor()
        register_unified_tools(app, db, executor)
        logger.info(f"MCP server ready with {len(list_tools())} tools")
    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down MCP server")
    await close_db()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        db = await get_db()
        async with db.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")


@app.get("/tools")
async def list_available_tools():
    """List all available tools."""
    tools = list_tools("read_only")
    return {
        "total_count": len(tools),
        "tools": tools,
    }


@app.post("/connect")
async def connect():
    """Create a new SSE connection."""
    connection_id = str(uuid.uuid4())
    connection = SSEConnection(connection_id)
    _connections[connection_id] = connection

    logger.info(f"New MCP connection: {connection_id}")

    return {
        "connection_id": connection_id,
        "sse_endpoint": f"/sse/{connection_id}",
    }


@app.get("/sse/{connection_id}")
async def sse_stream(connection_id: str):
    """SSE endpoint for streaming messages."""
    if connection_id not in _connections:
        raise HTTPException(status_code=404, detail="Connection not found")

    connection = _connections[connection_id]
    logger.info(f"SSE client connected: {connection_id}")

    return StreamingResponse(
        connection.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/call/{connection_id}/{tool_name}")
async def call_tool(connection_id: str, tool_name: str, request: Request):
    """Call a tool through an MCP connection."""
    if connection_id not in _connections:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        args = await request.json()
        
        # Handle event analysis tools specially
        if tool_name == "analyze_event_for_upsert_tool":
            db = await get_db()
            ai_processor = await get_ai_processor()
            result = await analyze_event_for_upsert(
                db=db,
                ai_processor=ai_processor,
                source_id=args.get("source_id"),
                title=args.get("title"),
                start_time=args.get("start_time"),
                location=args.get("location"),
                description=args.get("description"),
                end_time=args.get("end_time"),
                category=args.get("category"),
                is_virtual=args.get("is_virtual", False),
                virtual_url=args.get("virtual_url"),
                external_id=args.get("external_id"),
                source_url=args.get("source_url"),
            )
            connection = _connections[connection_id]
            await connection.send_message("tool_result", {"tool": tool_name, "result": result})
            return {"status": "success", "tool": tool_name}
        
        # Otherwise use executor for other tools
        executor = await get_executor()
        result = await executor.execute_tool(
            name=tool_name,
            args=args,
            source="mcp",
            city_id=args.get("city_id"),
            access_level="read_only",
        )

        connection = _connections[connection_id]

        if result.success:
            await connection.send_message("tool_result", {"tool": tool_name, "result": result.result})
            return {"status": "success", "tool": tool_name}
        else:
            await connection.send_message("tool_error", {"tool": tool_name, "error": result.error})
            return {"status": "error", "tool": tool_name, "error": result.error}

    except Exception as e:
        logger.exception(f"Error calling tool {tool_name}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze_event_for_upsert")
async def analyze_event_endpoint(
    source_id: int,
    title: str,
    start_time: str,
    location: str = None,
    description: str = None,
    end_time: str = None,
    category: str = None,
    is_virtual: bool = False,
    virtual_url: str = None,
    external_id: str = None,
    source_url: str = None,
):
    """Analyze an event and recommend action for scraper."""
    try:
        db = await get_db()
        ai_processor = await get_ai_processor()
        result = await analyze_event_for_upsert(
            db=db,
            ai_processor=ai_processor,
            source_id=source_id,
            title=title,
            start_time=start_time,
            location=location,
            description=description,
            end_time=end_time,
            category=category,
            is_virtual=is_virtual,
            virtual_url=virtual_url,
            external_id=external_id,
            source_url=source_url,
        )
        return result
    except Exception as e:
        logger.exception(f"Error analyzing event")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trigger_cascade_for_document")
async def trigger_cascade_endpoint(
    document_id: int,
    event_id: int,
    city_id: str,
):
    """Trigger summary cascade when a document is processed."""
    try:
        db = await get_db()
        result = await trigger_cascade_for_document(
            db=db,
            document_id=document_id,
            event_id=event_id,
            city_id=city_id,
        )
        return result
    except Exception as e:
        logger.exception(f"Error triggering cascade for document {document_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/disconnect/{connection_id}")
async def disconnect(connection_id: str):
    """Close an SSE connection."""
    if connection_id in _connections:
        del _connections[connection_id]
        logger.info(f"Connection closed: {connection_id}")

    return {"status": "disconnected"}


if __name__ == "__main__":
    import uvicorn

    config = get_config()
    port = int(os.environ.get("MCP_PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )

