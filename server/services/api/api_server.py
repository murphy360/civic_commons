"""
Civic Commons API Server

FastAPI server providing HTTP endpoints for the web frontend,
including chat API with Gemini function calling.

All tool calls are logged to the activity_log table for admin visibility.

Usage:
    uvicorn api_server:app --host 0.0.0.0 --port 8080

Environment Variables:
    DATABASE_URL - PostgreSQL connection string
    GEMINI_API_KEY - Google AI API key for chat
    API_CORS_ORIGINS - Comma-separated list of allowed origins
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# shared is copied to services/shared by Dockerfile
from ..shared.config import get_config, get_city_config
from ..shared.db import Database
from ..shared.db_init import initialize_database
from ..shared.activity_log import log_service_started, log_service_stopped
from ..shared.activity_api import router as activity_router, set_db_pool
from .chat import ChatService
from ..mcp.tool_executor import ToolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("civic_commons.api")


# Global instances
_db: Database | None = None
_chat: ChatService | None = None
_executor: ToolExecutor | None = None
_city_id: str | None = None


def get_default_city_id() -> str:
    """Get the default city ID from config."""
    global _city_id
    if _city_id is None:
        city_config = get_city_config()
        city_name = city_config.get("city_profile", {}).get("name", "community")
        _city_id = city_name.lower().replace(" ", "_").replace(",", "")
    return _city_id


async def get_db() -> Database:
    """Get the database instance, initializing if needed."""
    global _db
    if _db is None:
        config = get_config()
        _db = await Database.create(config.database_url)
        logger.info("Database connection pool initialized")
    return _db


async def get_chat() -> ChatService:
    """Get the chat service instance."""
    global _chat
    if _chat is None:
        db = await get_db()
        executor = await get_executor()
        _chat = ChatService(db, executor=executor)
        logger.info("Chat service initialized")
    return _chat


async def get_executor() -> ToolExecutor:
    """Get the tool executor instance."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor


async def close_services() -> None:
    """Close all service connections."""
    global _db, _chat, _executor
    
    if _chat is not None:
        await _chat.close()
        _chat = None
    
    if _executor is not None:
        _executor = None
        
    if _db is not None:
        await _db.close()
        _db = None
        
    logger.info("Services closed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage server lifecycle."""
    logger.info("Starting Civic Commons API Server")
    
    # Initialize database schema if needed
    db = await get_db()
    await initialize_database(db.pool)
    
    # Inject db pool into activity logging router
    set_db_pool(db.pool)
    
    # Initialize remaining services
    await get_chat()
    
    logger.info("API server ready")
    logger.info("=" * 60)
    logger.info("API SERVICE STARTED - Chat API ready")
    logger.info("=" * 60)
    
    # Log startup to activity_log for admin visibility
    await log_service_started(db.pool, "API SERVICE")
    
    try:
        yield
    finally:
        logger.info("Shutting down API server")
        await log_service_stopped(db.pool, "API SERVICE")
        await close_services()


# Create FastAPI app
app = FastAPI(
    title="Civic Commons API",
    description="API for accessing civic data and AI chat",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS - allow all localhost ports for development
cors_origins = os.getenv("API_CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now (can restrict in production)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add request/response logging middleware
@app.middleware("http")
async def log_request_response(request: Request, call_next):
    """Log all API requests and responses with results."""
    # Skip internal logging endpoints to avoid recursion
    if request.url.path.startswith("/internal/"):
        return await call_next(request)
    
    try:
        # Get request body for POST/PUT
        body = b""
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await request.body()
            # Re-wrap the body so it can be read again
            async def receive():
                return {"type": "http.request", "body": body}
            request._receive = receive
        
        # Call the endpoint
        response = await call_next(request)
        
        # Determine status
        status_code = response.status_code
        level = "error" if status_code >= 400 else "success" if status_code == 200 else "info"
        
        # Log to database asynchronously without blocking response
        # Use create_task to avoid blocking
        async def log_to_db():
            try:
                await log_activity(
                    category="api",
                    action=f"{request.method} {request.url.path}",
                    level=level,
                    message=f"{request.method} {request.url.path} - Status {status_code}",
                    entity_type="api_call",
                    entity_id=status_code,
                    entity_title=request.url.path,
                    source_name=request.client.host if request.client else None,
                    details={
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "query_params": dict(request.query_params) if request.query_params else None,
                    }
                )
            except Exception as e:
                logger.error(f"Failed to log API request: {e}")
        
        # Schedule the logging task
        asyncio.create_task(log_to_db())
        
        return response
    except Exception as e:
        logger.error(f"Error in request middleware: {e}", exc_info=True)
        raise

# Include internal activity logging router
app.include_router(activity_router)


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatMessage(BaseModel):
    """A single chat message."""
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    messages: list[ChatMessage]
    stream: bool = True


class ChatResponse(BaseModel):
    """Response body for non-streaming chat."""
    content: str
    tool_calls: list[dict[str, Any]] = []


class EventsRequest(BaseModel):
    """Request for events search."""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    source_type: Optional[str] = None
    limit: int = 50


class DocumentSearchRequest(BaseModel):
    """Request for document search."""
    query: str
    source_type: Optional[str] = None
    limit: int = 20


class UpsertEventRequest(BaseModel):
    """Request to upsert an event with optional MCP analysis."""
    # Core event data (from scraper)
    source_id: int
    title: str
    start_time: str  # ISO format: "2024-01-15T19:00:00"
    
    # Optional event details
    end_time: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_virtual: bool = False
    virtual_url: Optional[str] = None
    
    # Source tracking
    external_id: Optional[str] = None
    source_url: Optional[str] = None
    
    # City association
    city_id: Optional[str] = None
    
    # Data enrichment (e.g., from documents)
    ai_summary: Optional[str] = None


class UpsertEventResponse(BaseModel):
    """Response from event upsert."""
    event_id: int
    action: str  # "created" or "merged"
    confidence: Optional[float] = None
    message: str


# ============================================================================
# API Endpoints
# ============================================================================

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


@app.get("/activity/filters")
async def get_activity_filters():
    """Get available categories and levels for activity log filtering."""
    db = await get_db()
    try:
        async with db.pool.acquire() as conn:
            # Get distinct categories from activity_log
            categories = await conn.fetch("""
                SELECT DISTINCT category FROM activity_log 
                ORDER BY category
            """)
            
            # Get distinct levels from activity_log
            levels = await conn.fetch("""
                SELECT DISTINCT level FROM activity_log 
                WHERE level IS NOT NULL
                ORDER BY level
            """)
        
        category_list = [row['category'] for row in categories]
        level_list = [row['level'] for row in levels]
        
        return {
            "categories": category_list,
            "levels": level_list,
            "category_icons": {
                "download": "⬇️",
                "extraction": "📄",
                "ai": "🤖",
                "scrape": "🔄",
                "event": "📅",
                "tool_call": "🔧",
                "mcp": "🧠",
                "linking": "🔗",
                "summary": "📝",
                "system": "⚙️",
                "error": "❌",
                "api": "🌐",
            },
            "category_labels": {
                "download": "Downloads",
                "extraction": "Extractions",
                "ai": "AI Analysis",
                "scrape": "Scraping",
                "event": "Events",
                "tool_call": "Tool Calls",
                "mcp": "MCP",
                "linking": "Linking",
                "summary": "Summaries",
                "system": "System",
                "error": "Errors",
                "api": "API Calls",
            },
        }
    except Exception as e:
        logger.error(f"Failed to get activity filters: {e}")
        return {
            "categories": [],
            "levels": ["error", "warning", "info", "success"],
            "category_icons": {},
            "category_labels": {},
        }


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Chat with the AI assistant.
    
    Sends messages to Gemini with function calling to access civic data.
    Returns a streaming SSE response with tool calls and final message.
    """
    chat_service = await get_chat()
    
    if not chat_service.enabled:
        raise HTTPException(
            status_code=503, 
            detail="Chat service not configured. GEMINI_API_KEY is required."
        )
    
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    
    if request.stream:
        async def generate():
            """Generate SSE events."""
            async for chunk in chat_service.chat(messages, stream=True):
                # Format as SSE event
                data = json.dumps(chunk)
                yield f"data: {data}\n\n"
            
            # Send done event
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        # Non-streaming: collect full response
        content = ""
        tool_calls = []
        
        async for chunk in chat_service.chat(messages, stream=False):
            if chunk["type"] == "message":
                content = chunk["content"]
            elif chunk["type"] == "tool_call":
                tool_calls.append(chunk)
            elif chunk["type"] == "error":
                raise HTTPException(status_code=500, detail=chunk["content"])
        
        return ChatResponse(content=content, tool_calls=tool_calls)


@app.get("/events")
async def get_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 50,
):
    """
    Get events within a date range.
    
    Args:
        start_date: Start date (YYYY-MM-DD), defaults to today
        end_date: End date (YYYY-MM-DD), defaults to 30 days from start
        source_type: Filter by source type
        limit: Maximum results
    """
    db = await get_db()
    
    today = date.today()
    start = date.fromisoformat(start_date) if start_date else today
    end = date.fromisoformat(end_date) if end_date else start + timedelta(days=30)
    
    events = await db.get_events(
        city_id=get_default_city_id(),
        start_date=start,
        end_date=end,
        source_name=source_type,
        limit=limit,
    )
    
    return {
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "total": len(events),
        "events": [
            {
                "id": e["id"],
                "title": e["title"],
                "description": e.get("description"),
                "start_time": e["start_time"].isoformat() if e.get("start_time") else None,
                "end_time": e["end_time"].isoformat() if e.get("end_time") else None,
                "location": e.get("location"),
                "source": e.get("source_name"),
                "source_url": e.get("source_url"),
            }
            for e in events
        ]
    }


@app.get("/documents/search")
async def search_documents(
    query: str,
    source_type: Optional[str] = None,
    limit: int = 20,
):
    """
    Search documents by keyword.
    
    Args:
        query: Search query
        source_type: Filter by source type
        limit: Maximum results
    """
    db = await get_db()
    city_id = get_default_city_id()
    
    results = await db.search_documents(
        city_id=city_id,
        query=query,
        source_type=source_type,
        limit=limit,
    )
    
    return {
        "total": len(results),
        "count": len(results),
        "results": results,
    }


@app.get("/documents/{document_id}")
async def get_document(document_id: int):
    """
    Get a document by ID.
    
    Args:
        document_id: The document ID
    """
    db = await get_db()
    city_id = get_default_city_id()
    
    result = await db.get_document_content(
        city_id=city_id,
        document_id=document_id,
    )
    
    if result:
        return result
    else:
        raise HTTPException(status_code=404, detail="Document not found")


@app.get("/legislation")
async def get_legislation(
    legislation_type: Optional[str] = None,
    legislation_number: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
):
    """
    Get legislation mentions.
    
    Args:
        legislation_type: Filter by type (ordinance, resolution, motion)
        legislation_number: Filter by number
        search: Search in titles
        limit: Maximum results
    """
    # TODO: Implement legislation search in database
    return {
        "total": 0,
        "results": [],
    }


# Helper function to log activity via internal endpoint
async def log_activity(
    category: str,
    action: str,
    level: str = "info",
    message: str = "",
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_title: Optional[str] = None,
    source_name: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Log activity to the activity log via internal endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                "http://localhost:8080/internal/log",
                json={
                    "level": level,
                    "category": category,
                    "action": action,
                    "message": message,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "entity_title": entity_title,
                    "source_name": source_name,
                    "details": details,
                }
            )
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")


@app.post("/events/upsert")
async def upsert_event(request: UpsertEventRequest) -> UpsertEventResponse:
    """
    Upsert an event discovered by scraper.
    
    Flow:
    1. Use MCP to analyze the event (decide create vs merge)
    2. Implement decision in database
    3. Log both decision and action taken
    
    Args:
        request: Event data from scraper with source context
    
    Returns:
        Event ID and action taken (created or merged)
    """
    try:
        db = await get_db()
        
        # Parse ISO datetime strings to datetime objects
        start_time = None
        end_time = None
        
        if request.start_time:
            try:
                # Handle ISO format: "2025-12-28T19:30:00" or "2025-12-28T00:00:00"
                start_time = datetime.fromisoformat(request.start_time.replace('Z', '+00:00'))
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse start_time '{request.start_time}': {e}")
                start_time = None
        
        if request.end_time:
            try:
                end_time = datetime.fromisoformat(request.end_time.replace('Z', '+00:00'))
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse end_time '{request.end_time}': {e}")
                end_time = None
        
        # For now: Always create new events (MCP integration TODO)
        # In the future: Call MCP's analyze_event_for_upsert tool here
        
        async with db.pool.acquire() as conn:
            # Insert new event (only use columns that exist in events table)
            result = await conn.fetchrow("""
                INSERT INTO events (
                    title, start_time, end_time, 
                    location, description, category,
                    is_virtual, virtual_url, ai_summary,
                    created_at, updated_at
                )
                VALUES (
                    $1, $2, $3,
                    $4, $5, $6,
                    $7, $8, $9,
                    NOW(), NOW()
                )
                RETURNING id, title
            """, 
            request.title,
            start_time,
            end_time,
            request.location,
            request.description,
            request.category,
            request.is_virtual,
            request.virtual_url,
            request.ai_summary,
            )
            
            if result:
                event_id = result['id']
                
                # Link event to source via event_sources table
                await conn.execute("""
                    INSERT INTO event_sources (event_id, source_id, external_id, source_url)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (event_id, source_id) DO NOTHING
                """,
                event_id,
                request.source_id,
                request.external_id,
                request.source_url,
                )
                
                # Log the event creation
                await log_activity(
                    category="event",
                    action="created",
                    level="success",
                    message=f"Event created: {request.title}",
                    entity_type="event",
                    entity_id=event_id,
                    entity_title=request.title,
                    source_name=None,
                    details={"source_id": request.source_id, "action": "created"}
                )
                
                return UpsertEventResponse(
                    event_id=event_id,
                    action="created",
                    confidence=None,
                    message=f"Event created successfully with ID {event_id}",
                )
        
        # Fallback error
        await log_activity(
            category="event",
            action="error",
            level="error",
            message=f"Failed to create event: {request.title}",
            entity_type="event",
            entity_id=None,
            entity_title=request.title,
            source_name=None,
            details={"error": "Database insert returned no result"}
        )
        
        return UpsertEventResponse(
            event_id=0,
            action="error",
            confidence=None,
            message="Failed to create event",
        )
        
    except Exception as e:
        logger.error(f"Error in upsert_event: {e}", exc_info=True)
        await log_activity(
            category="event",
            action="error",
            level="error",
            message=f"Event upsert failed: {str(e)}",
            entity_type="event",
            entity_id=None,
            entity_title=request.title,
            source_name=None,
            details={"error": str(e)}
        )
        return UpsertEventResponse(
            event_id=0,
            action="error",
            confidence=None,
            message=f"Error: {str(e)}",
        )


# ============================================================================
# Main entry point
# ============================================================================

def main():
    """Run the API server."""
    import uvicorn
    
    config = get_config()
    uvicorn.run(
        "api_server:app",
        host=config.host,
        port=config.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()


