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

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# shared is copied to services/shared by Dockerfile
from ..shared.db import Database
from ..shared.config import get_config
from ..shared.activity_log import log_service_started, log_service_stopped
from .tool_executor import ToolExecutor
from .tool_registry import get_tool_definitions, list_tools
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
            # Lazy import from scraper pipeline - path is /app/workers/scraper
            import sys
            scraper_path = "/app/workers/scraper"
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
            # Lazy import from scraper pipeline - path is /app/workers/scraper
            import sys
            scraper_path = "/app/workers/scraper"
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
        logger.info("=" * 60)
        logger.info("MCP SERVICE STARTED - Tool server ready")
        logger.info("=" * 60)
        
        # Log startup to activity_log for admin visibility
        await log_service_started(db.pool, "MCP SERVICE")
    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down MCP server")
    try:
        db = await get_db()
        await log_service_stopped(db.pool, "MCP SERVICE")
    except Exception:
        pass  # DB may already be closed
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


# =============================================================================
# Async AI Processing Endpoints (fire-and-forget from cascade)
# =============================================================================

@app.post("/process_document", status_code=202)
async def process_document_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Queue a document for AI processing. Returns 202 Accepted immediately.
    
    MCP handles the full lifecycle:
    1. Marks document as ai_processing
    2. Generates AI summary with metadata extraction
    3. Updates document with summary
    4. Links document to event
    5. Marks as completed (or ai_pending on failure)
    """
    try:
        data = await request.json()
        doc_id = data.get("document_id")
        
        if not doc_id:
            raise HTTPException(status_code=400, detail="document_id is required")
        
        # Queue for background processing
        background_tasks.add_task(
            _process_document_async,
            doc_id=doc_id,
            content=data.get("content"),
            title=data.get("title", ""),
            document_type=data.get("document_type"),
            source_id=data.get("source_id"),
        )
        
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "document_id": doc_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error queuing document {data.get('document_id')}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process_video", status_code=202)
async def process_video_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Queue a video for AI processing. Returns 202 Accepted immediately.
    
    Videos can take 10+ minutes to process through Gemini.
    MCP handles the full lifecycle asynchronously.
    """
    try:
        data = await request.json()
        doc_id = data.get("document_id")
        
        if not doc_id:
            raise HTTPException(status_code=400, detail="document_id is required")
        
        # Queue for background processing
        background_tasks.add_task(
            _process_video_async,
            doc_id=doc_id,
            video_url=data.get("video_url"),
            title=data.get("title", ""),
            source_id=data.get("source_id"),
        )
        
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "document_id": doc_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error queuing video {data.get('document_id')}")
        raise HTTPException(status_code=500, detail=str(e))


async def _process_document_async(
    doc_id: int,
    content: str,
    title: str,
    document_type: str,
    source_id: int,
) -> None:
    """Background task: Process document through AI and update database."""
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            # Mark as processing
            await conn.execute("""
                UPDATE documents 
                SET content_status = 'ai_processing', ai_started_at = NOW(), updated_at = NOW()
                WHERE id = $1
            """, doc_id)
            
            logger.info(f"Processing document {doc_id}: {title[:50]}...")
            
            # Get summarizer
            summarizer = await get_doc_summarizer()
            if not summarizer:
                raise Exception("Document summarizer not available")
            
            # Generate summary with metadata
            result = await summarizer.generate_summary_with_metadata(
                title=title,
                document_type=document_type,
                content_text=content,
            )
            
            if result and result.text:
                # Update document with summary
                await conn.execute("""
                    UPDATE documents 
                    SET ai_summary = $1, 
                        ai_summary_updated_at = NOW(),
                        ai_model_used = $2,
                        content_status = 'completed',
                        ai_completed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $3
                """, result.text, result.model, doc_id)
                
                logger.info(f"Document {doc_id} summary complete ({len(result.text)} chars)")
                
                # Link to event using extracted metadata
                if source_id and result.meeting_date:
                    await _link_document_to_event(
                        conn, doc_id, title, document_type, source_id, result
                    )
            else:
                raise Exception("AI returned empty summary")
                
    except Exception as e:
        logger.warning(f"Document {doc_id} AI failed: {e}")
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE documents 
                    SET content_status = 'ai_pending',
                        retry_count = COALESCE(retry_count, 0) + 1,
                        error_message = $1,
                        updated_at = NOW()
                    WHERE id = $2
                """, str(e)[:500], doc_id)
        except Exception as db_err:
            logger.error(f"Failed to update document {doc_id} status: {db_err}")


async def _process_video_async(
    doc_id: int,
    video_url: str,
    title: str,
    source_id: int,
) -> None:
    """Background task: Process video through AI and update database."""
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            # Mark as processing
            await conn.execute("""
                UPDATE documents 
                SET content_status = 'ai_processing', ai_started_at = NOW(), updated_at = NOW()
                WHERE id = $1
            """, doc_id)
            
            logger.info(f"Processing video {doc_id}: {title[:50]}...")
            
            # Get summarizer
            summarizer = await get_doc_summarizer()
            if not summarizer:
                raise Exception("Document summarizer not available")
            
            # Generate summary with metadata (can take 10+ minutes)
            result = await summarizer.generate_summary_with_metadata(
                title=title,
                document_type="video",
                video_url=video_url,
            )
            
            if result and result.text:
                # Update document with summary
                await conn.execute("""
                    UPDATE documents 
                    SET ai_summary = $1, 
                        ai_summary_updated_at = NOW(),
                        ai_model_used = $2,
                        content_status = 'completed',
                        ai_completed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $3
                """, result.text, result.model, doc_id)
                
                logger.info(f"Video {doc_id} summary complete ({len(result.text)} chars)")
                
                # Link to event using extracted metadata
                if source_id and result.meeting_date:
                    await _link_document_to_event(
                        conn, doc_id, title, "video", source_id, result
                    )
            else:
                raise Exception("AI returned empty summary")
                
    except Exception as e:
        logger.warning(f"Video {doc_id} AI failed: {e}")
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE documents 
                    SET content_status = 'ai_pending',
                        retry_count = COALESCE(retry_count, 0) + 1,
                        error_message = $1,
                        updated_at = NOW()
                    WHERE id = $2
                """, str(e)[:500], doc_id)
        except Exception as db_err:
            logger.error(f"Failed to update video {doc_id} status: {db_err}")


async def _link_document_to_event(conn, doc_id: int, title: str, doc_type: str, source_id: int, result) -> None:
    """Link document to event using AI-extracted metadata."""
    try:
        from datetime import datetime
        
        meeting_date = result.meeting_date
        meeting_body = result.meeting_body
        
        # Parse date
        meeting_dt = datetime.strptime(meeting_date, "%Y-%m-%d")
        
        # Get city_id from source
        source_row = await conn.fetchrow(
            "SELECT city_id FROM sources WHERE id = $1", source_id
        )
        city_id = source_row['city_id'] if source_row else None
        
        # Find matching event
        event = await conn.fetchrow("""
            SELECT e.id, e.title
            FROM events e
            JOIN event_sources es ON e.id = es.event_id
            WHERE es.source_id = $1 AND DATE(e.start_time) = $2
            LIMIT 1
        """, source_id, meeting_dt.date())
        
        if event:
            # Link to existing event
            await conn.execute("""
                INSERT INTO event_documents (event_id, document_id, relationship)
                VALUES ($1, $2, $3)
                ON CONFLICT (event_id, document_id) DO NOTHING
            """, event['id'], doc_id, doc_type or 'related')
            
            logger.info(f"Linked document {doc_id} to event {event['id']}")
        else:
            # Create new event if this is agenda/minutes/video
            if doc_type in ('agenda', 'minutes', 'video'):
                # Use AI-extracted event_title if available, fallback to meeting_body
                event_title = getattr(result, 'event_title', None) or result.meeting_body or title.split(' - ')[0]
                event_title = _normalize_event_title(event_title)
                
                event_id = await conn.fetchval("""
                    INSERT INTO events (title, start_time, category, created_at, updated_at)
                    VALUES ($1, $2, $3, NOW(), NOW())
                    RETURNING id
                """, event_title, meeting_dt, result.meeting_type or "meeting")
                
                # Link to source
                await conn.execute("""
                    INSERT INTO event_sources (event_id, source_id, first_seen_at, last_seen_at)
                    VALUES ($1, $2, NOW(), NOW())
                    ON CONFLICT DO NOTHING
                """, event_id, source_id)
                
                # Link document
                await conn.execute("""
                    INSERT INTO event_documents (event_id, document_id, relationship)
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                """, event_id, doc_id, doc_type or 'related')
                
                logger.info(f"Created event {event_id} '{event_title}' and linked document {doc_id}")
                
    except Exception as e:
        logger.warning(f"Failed to link document {doc_id} to event: {e}")


def _normalize_event_title(title: str) -> str:
    """
    Normalize event title by removing document type suffixes.
    
    Examples:
        "City Council Agenda" -> "City Council"
        "Planning Commission - Minutes" -> "Planning Commission"
        "J.E.DI. Committee (Justice, Equity, Diversity & Inclusion) Agenda" -> "J.E.DI. Committee (Justice, Equity, Diversity & Inclusion)"
    """
    import re
    
    # Suffixes to remove (case insensitive)
    suffixes = [
        r'\s*-?\s*Agenda$',
        r'\s*-?\s*Minutes$',
        r'\s*-?\s*Video$',
        r'\s*-?\s*Meeting Agenda$',
        r'\s*-?\s*Meeting Minutes$',
        r'\s*-?\s*Agenda Meeting$',
        r'\s*-?\s*Regular Meeting$',
        r'\s*-?\s*Special Meeting$',
        r'\s*-?\s*Work Session$',
    ]
    
    normalized = title.strip()
    for suffix in suffixes:
        normalized = re.sub(suffix, '', normalized, flags=re.IGNORECASE)
    
    return normalized.strip()


# =============================================================================
# Synchronous AI Endpoints (kept for direct calls/testing)
# =============================================================================

@app.post("/summarize_document")
async def summarize_document_endpoint(request: Request):
    """Generate AI summary for a document with metadata extraction."""
    try:
        data = await request.json()
        doc_id = data.get("document_id")
        content = data.get("content")
        local_path = data.get("local_path")
        title = data.get("title", "")
        document_type = data.get("document_type", "document")
        
        if not content and not local_path:
            raise HTTPException(status_code=400, detail="content or local_path is required")
        
        summarizer = await get_doc_summarizer()
        if not summarizer:
            raise HTTPException(status_code=503, detail="Document summarizer not available")
        
        # Generate summary with metadata using unified method
        result = await summarizer.generate_summary_with_metadata(
            title=title,
            document_type=document_type,
            content_text=content,
            local_path=local_path,
        )
        
        if result:
            return {
                "success": True,
                "document_id": doc_id,
                "summary": result.text,
                "model": result.model,
                # Extracted metadata for event linking
                "metadata": {
                    "meeting_date": result.meeting_date,
                    "meeting_time": result.meeting_time,
                    "meeting_body": result.meeting_body,
                    "meeting_type": result.meeting_type,
                    "meeting_location": result.meeting_location,
                    "attendees_present": result.attendees_present,
                    "attendees_absent": result.attendees_absent,
                    "confidence": result.confidence,
                }
            }
        else:
            return {
                "success": False,
                "document_id": doc_id,
                "summary": None,
                "model": None,
                "metadata": None,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error summarizing document")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/summarize_video")
async def summarize_video_endpoint(request: Request):
    """Generate AI summary for a video (via YouTube transcript) with metadata."""
    try:
        data = await request.json()
        doc_id = data.get("document_id")
        video_url = data.get("video_url")
        title = data.get("title", "")
        
        if not video_url:
            raise HTTPException(status_code=400, detail="video_url is required")
        
        summarizer = await get_doc_summarizer()
        if not summarizer:
            raise HTTPException(status_code=503, detail="Document summarizer not available")
        
        # Generate summary from video with metadata extraction
        result = await summarizer.generate_summary_with_metadata(
            title=title,
            document_type="video",
            video_url=video_url,
        )
        
        if result:
            return {
                "success": True,
                "document_id": doc_id,
                "summary": result.text,
                "model": result.model,
                # Extracted metadata for event linking
                "metadata": {
                    "meeting_date": result.meeting_date,
                    "meeting_time": result.meeting_time,
                    "meeting_body": result.meeting_body,
                    "meeting_type": result.meeting_type,
                    "meeting_location": result.meeting_location,
                    "attendees_present": result.attendees_present,
                    "attendees_absent": result.attendees_absent,
                    "confidence": result.confidence,
                }
            }
        else:
            return {
                "success": False,
                "document_id": doc_id,
                "summary": None,
                "model": None,
                "metadata": None,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error summarizing video")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/summarize_event")
async def summarize_event_endpoint(request: Request):
    """Generate AI summary for an event from its documents."""
    try:
        data = await request.json()
        event_id = data.get("event_id")
        
        if not event_id:
            raise HTTPException(status_code=400, detail="event_id is required")
        
        db = await get_db()
        summarizer = await get_doc_summarizer()
        if not summarizer:
            raise HTTPException(status_code=503, detail="Document summarizer not available")
        
        # Get event and its documents
        async with db.pool.acquire() as conn:
            event = await conn.fetchrow(
                "SELECT id, title, start_time FROM events WHERE id = $1", event_id
            )
            if not event:
                raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
            
            # Get document summaries for this event
            docs = await conn.fetch("""
                SELECT d.title, d.document_type, d.ai_summary
                FROM documents d
                JOIN event_documents ed ON d.id = ed.document_id
                WHERE ed.event_id = $1
                  AND d.ai_summary IS NOT NULL
                  AND d.ai_summary != ''
                ORDER BY d.document_type, d.title
            """, event_id)
        
        if not docs:
            return {
                "success": False,
                "event_id": event_id,
                "error": "No document summaries available for this event",
            }
        
        # Combine document summaries into event summary
        combined_content = f"Event: {event['title']}\n"
        if event['start_time']:
            combined_content += f"Date: {event['start_time'].strftime('%B %d, %Y')}\n\n"
        
        combined_content += "Documents:\n"
        for doc in docs:
            combined_content += f"\n--- {doc['document_type'].title()}: {doc['title']} ---\n"
            combined_content += doc['ai_summary'] + "\n"
        
        # Generate event summary using generate_summary with content_text
        result = await summarizer.generate_summary(
            title=f"Summary of {event['title']}",
            document_type="event_summary",
            content_text=combined_content,
        )
        
        summary = result.text if result else None
        model = result.model if result else None
        
        return {
            "success": bool(summary),
            "event_id": event_id,
            "summary": summary,
            "model": model,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error summarizing event")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_period_summary")
async def generate_period_summary_endpoint(request: Request):
    """Generate a period summary (weekly, monthly, etc.)."""
    try:
        data = await request.json()
        summary_id = data.get("summary_id")
        summary_type = data.get("summary_type", "weekly")
        
        if not summary_id:
            raise HTTPException(status_code=400, detail="summary_id is required")
        
        db = await get_db()
        generator = await get_summary_generator()
        if not generator:
            raise HTTPException(status_code=503, detail="Summary generator not available")
        
        # Get summary record and generate
        async with db.pool.acquire() as conn:
            summary_record = await conn.fetchrow(
                "SELECT * FROM summaries WHERE id = $1", summary_id
            )
            if not summary_record:
                raise HTTPException(status_code=404, detail=f"Summary {summary_id} not found")
            
            # Get events in period
            events = await conn.fetch("""
                SELECT id, title, start_time, ai_summary
                FROM events
                WHERE start_time >= $1 AND start_time < $2
                  AND ai_summary IS NOT NULL AND ai_summary != ''
                ORDER BY start_time
            """, summary_record['period_start'], summary_record['period_end'])
            
            if not events:
                return {
                    "success": False,
                    "summary_id": summary_id,
                    "error": "No summarized events in this period",
                }
            
            # Generate period summary
            content = await generator.generate_period_summary(
                events=events,
                summary_type=summary_type,
                period_start=summary_record['period_start'],
                period_end=summary_record['period_end'],
            )
            
            # Update summary record
            await conn.execute("""
                UPDATE summaries 
                SET content = $1, status = 'published', generated_at = NOW(), updated_at = NOW()
                WHERE id = $2
            """, content, summary_id)
        
        return {
            "success": True,
            "summary_id": summary_id,
            "model": "gemini-1.5-flash",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating period summary")
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

