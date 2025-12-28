"""
Admin API Endpoints

Provides admin-only endpoints for operational dashboards:
- Activity log viewing and filtering
- Queue status and management
- Scraper source control
- System health overview
- AI processing logs
- Newsletter management
- Legislation tracking
- Summary regeneration

All endpoints require proper authentication/authorization (to be added).
All endpoints accept city_id as parameter (no hardcoding).
"""

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

if TYPE_CHECKING:
    from . import Database

logger = logging.getLogger("civic_commons.admin")

# Create admin router
router = APIRouter(prefix="/admin", tags=["admin"])

# Will be set by api_server after initialization
_get_db_func = None


def set_db_getter(get_db_func):
    """Set the database getter function."""
    global _get_db_func
    _get_db_func = get_db_func


async def get_db() -> "Database":
    """Get the database instance."""
    if _get_db_func is None:
        raise RuntimeError("Database getter not initialized")
    return await _get_db_func()


# ============================================================================
# Request/Response Models
# ============================================================================

class ActivityLogEntry(BaseModel):
    """Single activity log entry."""
    id: int
    timestamp: datetime
    level: str
    category: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    entity_title: Optional[str] = None
    message: str
    source_name: Optional[str] = None
    city_id: Optional[str] = None


class ActivityResponse(BaseModel):
    """Activity log response."""
    activities: list[ActivityLogEntry]
    total_count: int
    has_more: bool
    filters_applied: dict[str, Any]


class ActivityFiltersResponse(BaseModel):
    """Available activity log filters."""
    categories: list[str]
    levels: list[str]
    category_icons: dict[str, str]
    category_labels: dict[str, str]


class QueueStats(BaseModel):
    """Queue statistics for a processing stage."""
    pending: int
    in_progress: int
    completed_today: int
    failed_today: int
    oldest_pending: Optional[datetime] = None
    newest_pending: Optional[datetime] = None


class QueueStatusResponse(BaseModel):
    """Overall queue status."""
    download_queue: QueueStats
    extraction_queue: QueueStats
    ai_document_queue: QueueStats
    ai_video_queue: QueueStats
    ai_event_queue: QueueStats
    ai_summary_queue: QueueStats
    linking_queue: QueueStats
    health_status: str
    total_failures_today: int
    timestamp: datetime


class QueueItem(BaseModel):
    """Single queue item."""
    id: int
    title: str
    item_type: str  # document/video
    content_status: str
    source_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class QueueItemsResponse(BaseModel):
    """Queue items listing."""
    items: list[QueueItem]
    total_count: int
    has_more: bool


class QueueActionRequest(BaseModel):
    """Request to perform queue action."""
    action: str  # retry_failed, reset_stuck, skip
    item_ids: Optional[list[int]] = None
    batch_size: int = 3


class QueueActionResponse(BaseModel):
    """Response from queue action."""
    affected_count: int
    message: str


class Source(BaseModel):
    """Data source."""
    id: int
    name: str
    city_id: str
    source_type: str
    is_enabled: bool
    last_fetched_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    trigger_requested_at: Optional[datetime] = None


class ScrapeSourcesResponse(BaseModel):
    """List of scrape sources."""
    sources: list[Source]


class ScrapeActionRequest(BaseModel):
    """Request to trigger scrape."""
    source_id: Optional[int] = None
    all: bool = False


class ScrapeActionResponse(BaseModel):
    """Response from scrape trigger."""
    triggered_count: int
    sources: list[dict[str, Any]]


class SystemStatusResponse(BaseModel):
    """System health and status overview."""
    sources: dict[str, Any]
    events: dict[str, int]
    documents: dict[str, int]
    ai_queue: dict[str, int]
    backfill_status: Optional[dict[str, Any]] = None
    recent_activity: list[dict[str, Any]]
    timestamp: datetime


class Newsletter(BaseModel):
    """Newsletter record."""
    id: int
    period_type: str
    period_start: datetime
    period_end: datetime
    status: str
    event_count: Optional[int] = None
    document_count: Optional[int] = None
    created_at: datetime


class NewsletterListResponse(BaseModel):
    """Newsletter list."""
    newsletters: list[Newsletter]
    stats: dict[str, int]


class NewsletterCreateRequest(BaseModel):
    """Request to create newsletter."""
    period_type: str  # daily, weekly, monthly, quarterly, annual
    city_id: str


class NewsletterCreateResponse(BaseModel):
    """Response from newsletter creation."""
    id: int
    period_type: str
    period_start: datetime
    period_end: datetime
    message: str


class LegislationItem(BaseModel):
    """Legislation mention."""
    id: int
    legislation_type: str
    legislation_number: str
    title: str
    linked_event_count: int
    total_mentions: int


class LegislationListResponse(BaseModel):
    """Legislation list."""
    items: list[LegislationItem]
    total_count: int
    has_more: bool


class LegislationLinkRequest(BaseModel):
    """Request to link/unlink legislation."""
    action: str  # link, unlink
    legislation_id: int
    event_ids: list[int]


class LegislationLinkResponse(BaseModel):
    """Response from legislation linking."""
    affected_count: int
    message: str


class SummaryReanalyzeRequest(BaseModel):
    """Request to trigger summary reanalysis."""
    summary_id: Optional[int] = None
    summary_type: Optional[str] = None  # daily, weekly, monthly, quarterly, annual
    period_date: Optional[str] = None  # ISO date format
    city_id: str


class SummaryReanalyzeResponse(BaseModel):
    """Response from summary reanalysis trigger."""
    summary_id: int
    is_new: bool
    period_type: str
    period_date: str
    message: str


# ============================================================================
# Activity Log Endpoints
# ============================================================================

@router.get("/activity")
async def get_activity_logs(
    city_id: str = Query(..., description="City identifier"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    level: Optional[str] = Query(None, description="Filter by level"),
    category: Optional[str] = Query(None, description="Filter by category"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    hours: int = Query(24, ge=1, le=720, description="Time range in hours"),
) -> ActivityResponse:
    """
    Get activity log entries with filtering.
    
    Args:
        city_id: City identifier (required)
        limit: Maximum results (default 100)
        offset: Pagination offset (default 0)
        level: Filter by level (info, success, warning, error)
        category: Filter by category
        entity_type: Filter by entity type
        hours: Time range in hours (default 24)
    """
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            # Build base query
            query = """
                SELECT 
                    id, timestamp, level, category, action,
                    entity_type, entity_id, entity_title, message,
                    source_name, city_id
                FROM activity_log
                WHERE timestamp >= NOW() - make_interval(hours => $1)
            """
            params = [hours]
            param_num = 2
            
            # Add filters
            if level:
                query += f" AND level = ${param_num}"
                params.append(level)
                param_num += 1
            
            if category:
                query += f" AND category = ${param_num}"
                params.append(category)
                param_num += 1
            
            if entity_type:
                query += f" AND entity_type = ${param_num}"
                params.append(entity_type)
                param_num += 1
            
            # Get total count
            count_query = f"SELECT COUNT(*) as count FROM ({query}) as t"
            count_result = await conn.fetchval(count_query, *params)
            total_count = count_result or 0
            
            # Get paginated results
            query += f" ORDER BY timestamp DESC LIMIT ${param_num} OFFSET ${param_num + 1}"
            params.extend([limit, offset])
            
            rows = await conn.fetch(query, *params)
            
            activities = [
                ActivityLogEntry(
                    id=row['id'],
                    timestamp=row['timestamp'],
                    level=row['level'],
                    category=row['category'],
                    action=row['action'],
                    entity_type=row['entity_type'],
                    entity_id=row['entity_id'],
                    entity_title=row['entity_title'],
                    message=row['message'],
                    source_name=row['source_name'],
                    city_id=row['city_id'],
                )
                for row in rows
            ]
            
            has_more = (offset + limit) < total_count
            
            return ActivityResponse(
                activities=activities,
                total_count=total_count,
                has_more=has_more,
                filters_applied={
                    "city_id": city_id,
                    "hours": hours,
                    "level": level,
                    "category": category,
                    "entity_type": entity_type,
                }
            )
    except Exception as e:
        logger.error(f"Error fetching activity logs: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/activity/filters")
async def get_activity_filters(
    city_id: str = Query(..., description="City identifier"),
) -> ActivityFiltersResponse:
    """
    Get available activity log filters and metadata.
    
    Args:
        city_id: City identifier (required)
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            # Get distinct categories
            categories = await conn.fetch("""
                SELECT DISTINCT category FROM activity_log 
                ORDER BY category
            """)
            
            # Get distinct levels
            levels = await conn.fetch("""
                SELECT DISTINCT level FROM activity_log 
                WHERE level IS NOT NULL
                ORDER BY level
            """)
        
        category_list = [row['category'] for row in categories if row['category']]
        level_list = [row['level'] for row in levels if row['level']]
        
        return ActivityFiltersResponse(
            categories=category_list,
            levels=level_list,
            category_icons={
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
            category_labels={
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
        )
    except Exception as e:
        logger.error(f"Error fetching activity filters: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Queue Management Endpoints
# ============================================================================

@router.get("/queue")
async def get_queue_status(
    city_id: str = Query(..., description="City identifier"),
    detailed: bool = Query(False, description="Include detailed items"),
) -> QueueStatusResponse:
    """
    Get comprehensive queue status across all processing stages.
    
    Args:
        city_id: City identifier (required)
        detailed: Include active and failed items (optional)
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            # Download queue stats
            download = await conn.fetchrow("""
                SELECT 
                    COUNT(*) FILTER (WHERE content_status IN ('discovered', 'download_pending'))::int as pending,
                    COUNT(*) FILTER (WHERE content_status = 'downloading')::int as in_progress,
                    COUNT(*) FILTER (WHERE content_status NOT IN ('discovered', 'download_pending', 'downloading', 'failed', 'skipped') 
                        AND download_completed_at >= CURRENT_DATE)::int as completed_today,
                    COUNT(*) FILTER (WHERE content_status = 'failed' 
                        AND error_message ILIKE '%download%'
                        AND updated_at >= CURRENT_DATE)::int as failed_today,
                    MIN(meeting_date) FILTER (WHERE content_status IN ('discovered', 'download_pending')) as oldest_pending,
                    MAX(meeting_date) FILTER (WHERE content_status IN ('discovered', 'download_pending')) as newest_pending
                FROM documents
            """)
            
            # Count failures for health check
            failure_count = await conn.fetchval("""
                SELECT COUNT(*)::int 
                FROM documents 
                WHERE updated_at >= CURRENT_DATE AND content_status = 'failed'
            """)
            
            health_status = "healthy" if (failure_count or 0) < 20 else "degraded"
            
            return QueueStatusResponse(
                download_queue=QueueStats(
                    pending=download['pending'] or 0,
                    in_progress=download['in_progress'] or 0,
                    completed_today=download['completed_today'] or 0,
                    failed_today=download['failed_today'] or 0,
                    oldest_pending=download['oldest_pending'],
                    newest_pending=download['newest_pending'],
                ),
                extraction_queue=QueueStats(pending=0, in_progress=0, completed_today=0, failed_today=0),
                ai_document_queue=QueueStats(pending=0, in_progress=0, completed_today=0, failed_today=0),
                ai_video_queue=QueueStats(pending=0, in_progress=0, completed_today=0, failed_today=0),
                ai_event_queue=QueueStats(pending=0, in_progress=0, completed_today=0, failed_today=0),
                ai_summary_queue=QueueStats(pending=0, in_progress=0, completed_today=0, failed_today=0),
                linking_queue=QueueStats(pending=0, in_progress=0, completed_today=0, failed_today=0),
                health_status=health_status,
                total_failures_today=failure_count or 0,
                timestamp=datetime.now(),
            )
    except Exception as e:
        logger.error(f"Error fetching queue status: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/queue/items")
async def get_queue_items(
    city_id: str = Query(..., description="City identifier"),
    status: Optional[str] = Query(None, description="Filter by content_status"),
    item_type: Optional[str] = Query(None, description="document or video"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> QueueItemsResponse:
    """
    Get paginated queue items with filtering.
    
    Args:
        city_id: City identifier (required)
        status: Filter by content_status
        item_type: Filter by type (document/video)
        limit: Maximum results (default 50)
        offset: Pagination offset
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            query = "SELECT id, title, 'document' as item_type, content_status, created_at, updated_at FROM documents WHERE 1=1"
            params = []
            
            if status:
                query += " AND content_status = $" + str(len(params) + 1)
                params.append(status)
            
            # Get total count
            count_query = f"SELECT COUNT(*) FROM ({query}) as t"
            total_count = await conn.fetchval(count_query, *params)
            
            # Get paginated results
            query += f" ORDER BY updated_at DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
            params.extend([limit, offset])
            
            rows = await conn.fetch(query, *params)
            
            items = [
                QueueItem(
                    id=row['id'],
                    title=row['title'],
                    item_type=row['item_type'],
                    content_status=row['content_status'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                )
                for row in rows
            ]
            
            has_more = (offset + limit) < (total_count or 0)
            
            return QueueItemsResponse(
                items=items,
                total_count=total_count or 0,
                has_more=has_more,
            )
    except Exception as e:
        logger.error(f"Error fetching queue items: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/queue/items/action")
async def perform_queue_action(
    city_id: str = Query(..., description="City identifier"),
    request: QueueActionRequest = None,
) -> QueueActionResponse:
    """
    Perform bulk action on queue items (retry_failed, reset_stuck, skip).
    
    Args:
        city_id: City identifier (required)
        request: Action request details
    """
    
    db = await get_db()
    
    if not request or request.action not in ["retry_failed", "reset_stuck", "skip"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    try:
        async with db.pool.acquire() as conn:
            if request.action == "retry_failed":
                # Reset failed items
                affected = await conn.execute(
                    "UPDATE documents SET content_status = 'download_pending', error_message = NULL WHERE content_status = 'failed'"
                )
            elif request.action == "reset_stuck":
                # Reset items stuck in processing > 30 minutes
                affected = await conn.execute("""
                    UPDATE documents 
                    SET content_status = 'download_pending'
                    WHERE content_status IN ('downloading', 'extracting')
                    AND updated_at < NOW() - INTERVAL '30 minutes'
                """)
            else:  # skip
                affected = await conn.execute(
                    "UPDATE documents SET content_status = 'skipped' WHERE content_status IN ('discovered', 'download_pending')"
                )
            
            return QueueActionResponse(
                affected_count=affected or 0,
                message=f"Completed {request.action}: {affected or 0} items updated"
            )
    except Exception as e:
        logger.error(f"Error performing queue action: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Scraper Management Endpoints
# ============================================================================

@router.get("/sources")
async def get_sources(
    city_id: str = Query(..., description="City identifier"),
) -> ScrapeSourcesResponse:
    """
    Get list of data sources for a city.
    
    Args:
        city_id: City identifier (required)
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, city_id, source_type, is_enabled,
                       last_fetched_at, last_success_at, trigger_requested_at
                FROM sources
                WHERE city_id = $1
                ORDER BY name ASC
            """, city_id)
            
            sources = [
                Source(
                    id=row['id'],
                    name=row['name'],
                    city_id=row['city_id'],
                    source_type=row['source_type'],
                    is_enabled=row['is_enabled'],
                    last_fetched_at=row['last_fetched_at'],
                    last_success_at=row['last_success_at'],
                    trigger_requested_at=row['trigger_requested_at'],
                )
                for row in rows
            ]
            
            return ScrapeSourcesResponse(sources=sources)
    except Exception as e:
        logger.error(f"Error fetching sources: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/sources/trigger-scrape")
async def trigger_scrape(
    city_id: str = Query(..., description="City identifier"),
    request: ScrapeActionRequest = None,
) -> ScrapeActionResponse:
    """
    Trigger scrape for one or all sources.
    
    Args:
        city_id: City identifier (required)
        request: Trigger request with source_id or all=true
    """
    
    db = await get_db()
    
    if not request or (not request.source_id and not request.all):
        raise HTTPException(status_code=400, detail="Specify source_id or all=true")
    
    try:
        async with db.pool.acquire() as conn:
            if request.all:
                # Trigger all enabled sources for this city
                affected = await conn.execute("""
                    UPDATE sources 
                    SET trigger_requested_at = NOW()
                    WHERE city_id = $1 AND is_enabled = true
                """, city_id)
                
                # Get the triggered sources
                rows = await conn.fetch("""
                    SELECT id, name FROM sources
                    WHERE city_id = $1 AND is_enabled = true
                    ORDER BY name
                """, city_id)
            else:
                # Trigger single source
                affected = await conn.execute("""
                    UPDATE sources 
                    SET trigger_requested_at = NOW()
                    WHERE id = $1 AND city_id = $2
                """, request.source_id, city_id)
                
                rows = await conn.fetch("""
                    SELECT id, name FROM sources WHERE id = $1
                """, request.source_id)
            
            sources_triggered = [{"id": row['id'], "name": row['name']} for row in rows]
            
            return ScrapeActionResponse(
                triggered_count=affected or 0,
                sources=sources_triggered,
            )
    except Exception as e:
        logger.error(f"Error triggering scrape: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/status")
async def get_system_status(
    city_id: str = Query(..., description="City identifier"),
) -> SystemStatusResponse:
    """
    Get comprehensive system health and status overview.
    
    Args:
        city_id: City identifier (required)
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            # Source statistics
            source_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*)::int as total,
                    COUNT(*) FILTER (WHERE is_enabled)::int as active,
                    COUNT(*) FILTER (WHERE consecutive_failures < 3)::int as healthy,
                    COUNT(*) FILTER (WHERE consecutive_failures >= 3)::int as failing
                FROM sources
                WHERE city_id = $1
            """, city_id)
            
            # Event statistics
            event_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*)::int as total,
                    COUNT(*) FILTER (WHERE ai_summary IS NOT NULL AND ai_summary != '')::int as with_summaries
                FROM events
                WHERE start_time >= NOW() - INTERVAL '90 days'
            """)
            
            # Document statistics
            doc_stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*)::int as total,
                    COUNT(*) FILTER (WHERE content_text IS NOT NULL)::int as downloaded,
                    COUNT(*) FILTER (WHERE ai_summary IS NOT NULL AND ai_summary != '')::int as with_summaries
                FROM documents
            """)
            
            # Recent activity
            recent = await conn.fetch("""
                SELECT id, name, last_success_at, consecutive_failures
                FROM sources
                WHERE city_id = $1
                ORDER BY last_success_at DESC NULLS LAST
                LIMIT 20
            """, city_id)
            
            return SystemStatusResponse(
                sources={
                    "total": source_stats['total'] or 0,
                    "active": source_stats['active'] or 0,
                    "healthy": source_stats['healthy'] or 0,
                    "failing": source_stats['failing'] or 0,
                },
                events={
                    "total": event_stats['total'] or 0,
                    "with_summaries": event_stats['with_summaries'] or 0,
                },
                documents={
                    "total": doc_stats['total'] or 0,
                    "downloaded": doc_stats['downloaded'] or 0,
                    "with_summaries": doc_stats['with_summaries'] or 0,
                },
                ai_queue={
                    "pending_docs": 0,
                    "pending_summaries": 0,
                },
                backfill_status=None,
                recent_activity=[
                    {
                        "id": row['id'],
                        "name": row['name'],
                        "last_success": row['last_success_at'].isoformat() if row['last_success_at'] else None,
                        "failures": row['consecutive_failures'],
                    }
                    for row in recent
                ],
                timestamp=datetime.now(),
            )
    except Exception as e:
        logger.error(f"Error fetching system status: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/ai-logs")
async def get_ai_logs(
    city_id: str = Query(..., description="City identifier"),
) -> dict[str, Any]:
    """
    Get AI processing logs grouped by status.
    
    Args:
        city_id: City identifier (required)
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            # Get AI logs by category
            logs = await conn.fetch("""
                SELECT 
                    CASE 
                        WHEN ai_summary IS NOT NULL AND ai_summary != '' AND ai_summary NOT LIKE '[AI_SUMMARY_FAILED]%' THEN 'completed'
                        WHEN ai_summary = '[AI_SUMMARY_FAILED]%' THEN 'failed'
                        ELSE 'pending'
                    END as status,
                    COUNT(*)::int as count,
                    'documents' as item_type
                FROM documents
                WHERE updated_at >= NOW() - INTERVAL '7 days'
                GROUP BY status
            """)
            
            return {
                "completed": [row for row in logs if row['status'] == 'completed'],
                "pending": [row for row in logs if row['status'] == 'pending'],
                "failed": [row for row in logs if row['status'] == 'failed'],
            }
    except Exception as e:
        logger.error(f"Error fetching AI logs: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Newsletter Management Endpoints
# ============================================================================

@router.get("/newsletters")
async def get_newsletters(
    city_id: str = Query(..., description="City identifier"),
) -> NewsletterListResponse:
    """
    Get newsletters for a city.
    
    Args:
        city_id: City identifier (required)
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            newsletters = await conn.fetch("""
                SELECT id, period_type, period_start, period_end, status, created_at
                FROM newsletters
                WHERE city_id = $1
                ORDER BY created_at DESC
                LIMIT 50
            """, city_id)
            
            # Get stats
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*)::int as total,
                    COUNT(*) FILTER (WHERE status = 'completed')::int as completed,
                    COUNT(*) FILTER (WHERE status = 'pending')::int as pending,
                    COUNT(*) FILTER (WHERE status = 'failed')::int as failed
                FROM newsletters
                WHERE city_id = $1
            """, city_id)
            
            items = [
                Newsletter(
                    id=row['id'],
                    period_type=row['period_type'],
                    period_start=row['period_start'],
                    period_end=row['period_end'],
                    status=row['status'],
                    created_at=row['created_at'],
                )
                for row in newsletters
            ]
            
            return NewsletterListResponse(
                newsletters=items,
                stats={
                    "total": stats['total'] or 0,
                    "completed": stats['completed'] or 0,
                    "pending": stats['pending'] or 0,
                    "failed": stats['failed'] or 0,
                }
            )
    except Exception as e:
        logger.error(f"Error fetching newsletters: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/newsletters")
async def create_newsletter(
    request: NewsletterCreateRequest,
) -> NewsletterCreateResponse:
    """
    Create a new newsletter for a city.
    
    Args:
        request: Newsletter creation request with period_type and city_id
    """
    
    db = await get_db()
    
    if request.period_type not in ["daily", "weekly", "monthly", "quarterly", "annual"]:
        raise HTTPException(status_code=400, detail="Invalid period_type")
    
    try:
        async with db.pool.acquire() as conn:
            # Calculate period dates based on type
            today = datetime.now().date()
            
            if request.period_type == "daily":
                period_start = datetime.combine(today, datetime.min.time())
                period_end = datetime.combine(today + timedelta(days=1), datetime.min.time())
            elif request.period_type == "weekly":
                start_of_week = today - timedelta(days=today.weekday())
                period_start = datetime.combine(start_of_week, datetime.min.time())
                period_end = datetime.combine(start_of_week + timedelta(days=7), datetime.min.time())
            elif request.period_type == "monthly":
                period_start = datetime.combine(today.replace(day=1), datetime.min.time())
                if today.month == 12:
                    period_end = datetime.combine(date(today.year + 1, 1, 1), datetime.min.time())
                else:
                    period_end = datetime.combine(date(today.year, today.month + 1, 1), datetime.min.time())
            elif request.period_type == "quarterly":
                quarter = (today.month - 1) // 3
                period_start = datetime.combine(date(today.year, quarter * 3 + 1, 1), datetime.min.time())
                period_end = datetime.combine(date(today.year, (quarter + 1) * 3 + 1, 1), datetime.min.time())
            else:  # annual
                period_start = datetime.combine(date(today.year, 1, 1), datetime.min.time())
                period_end = datetime.combine(date(today.year + 1, 1, 1), datetime.min.time())
            
            # Check for existing newsletter
            existing = await conn.fetchval(
                "SELECT id FROM newsletters WHERE city_id = $1 AND period_type = $2 AND period_start = $3",
                request.city_id,
                request.period_type,
                period_start,
            )
            
            if existing:
                raise HTTPException(status_code=409, detail="Newsletter already exists for this period")
            
            # Create new newsletter
            result = await conn.fetchrow("""
                INSERT INTO newsletters (
                    city_id, period_type, period_start, period_end,
                    status, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, 'pending', NOW(), NOW())
                RETURNING id, period_type, period_start, period_end
            """, request.city_id, request.period_type, period_start, period_end)
            
            return NewsletterCreateResponse(
                id=result['id'],
                period_type=result['period_type'],
                period_start=result['period_start'],
                period_end=result['period_end'],
                message=f"Newsletter created for {request.period_type}",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating newsletter: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Legislation Endpoints
# ============================================================================

@router.get("/legislation")
async def get_legislation(
    city_id: str = Query(..., description="City identifier"),
    link_status: str = Query("all", regex="^(all|linked|unlinked)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> LegislationListResponse:
    """
    Get legislation with optional filtering by link status.
    
    Args:
        city_id: City identifier (required)
        link_status: Filter by link status (all, linked, unlinked)
        limit: Maximum results
        offset: Pagination offset
    """
    
    db = await get_db()
    
    try:
        async with db.pool.acquire() as conn:
            query = """
                SELECT DISTINCT
                    d.id,
                    d.title,
                    'ordinance' as legislation_type,
                    d.source_url as legislation_number,
                    COUNT(DISTINCT ed.event_id)::int as linked_event_count,
                    COUNT(DISTINCT d.id)::int as total_mentions
                FROM documents d
                LEFT JOIN event_documents ed ON d.id = ed.document_id
                WHERE d.document_type = 'legislation'
            """
            
            if link_status == "linked":
                query += " AND ed.event_id IS NOT NULL"
            elif link_status == "unlinked":
                query += " AND ed.event_id IS NULL"
            
            query += " GROUP BY d.id, d.title, d.source_url"
            
            params = []
            count_query = f"SELECT COUNT(*) FROM ({query}) as t"
            total_count = await conn.fetchval(count_query, *params)
            
            query += f" ORDER BY d.id DESC LIMIT {limit} OFFSET {offset}"
            rows = await conn.fetch(query, *params)
            
            items = [
                LegislationItem(
                    id=row['id'],
                    legislation_type=row['legislation_type'],
                    legislation_number=row['legislation_number'] or "",
                    title=row['title'],
                    linked_event_count=row['linked_event_count'] or 0,
                    total_mentions=row['total_mentions'] or 0,
                )
                for row in rows
            ]
            
            has_more = (offset + limit) < (total_count or 0)
            
            return LegislationListResponse(
                items=items,
                total_count=total_count or 0,
                has_more=has_more,
            )
    except Exception as e:
        logger.error(f"Error fetching legislation: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/legislation/link")
async def link_legislation(
    city_id: str = Query(..., description="City identifier"),
    request: LegislationLinkRequest = None,
) -> LegislationLinkResponse:
    """
    Link or unlink legislation from events.
    
    Args:
        city_id: City identifier (required)
        request: Link/unlink action with legislation_id and event_ids
    """
    
    db = await get_db()
    
    if not request or request.action not in ["link", "unlink"]:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    try:
        async with db.pool.acquire() as conn:
            if request.action == "link":
                affected = 0
                for event_id in request.event_ids:
                    result = await conn.execute("""
                        INSERT INTO event_documents (event_id, document_id)
                        VALUES ($1, $2)
                        ON CONFLICT DO NOTHING
                    """, event_id, request.legislation_id)
                    affected += result or 0
            else:  # unlink
                # Convert event_ids to proper format for IN clause
                affected = await conn.execute(
                    f"""DELETE FROM event_documents 
                       WHERE document_id = $1 AND event_id = ANY($2)""",
                    request.legislation_id,
                    request.event_ids,
                )
            
            return LegislationLinkResponse(
                affected_count=affected or 0,
                message=f"Completed {request.action}: {affected or 0} links updated",
            )
    except Exception as e:
        logger.error(f"Error linking legislation: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ============================================================================
# Summary Management Endpoints
# ============================================================================

@router.post("/summaries/reanalyze")
async def reanalyze_summary(
    request: SummaryReanalyzeRequest,
) -> SummaryReanalyzeResponse:
    """
    Trigger summary reanalysis by ID or period type.
    
    Args:
        request: Reanalysis request with either summary_id or summary_type+period_date
    """
    
    db = await get_db()
    
    if not request.summary_id and not (request.summary_type and request.period_date):
        raise HTTPException(status_code=400, detail="Specify summary_id or summary_type+period_date")
    
    try:
        async with db.pool.acquire() as conn:
            if request.summary_id:
                # Update by ID
                result = await conn.fetchrow("""
                    UPDATE summaries
                    SET is_stale = true, status = 'pending'
                    WHERE id = $1
                    RETURNING id, summary_type, summary_date
                """, request.summary_id)
                
                if not result:
                    raise HTTPException(status_code=404, detail="Summary not found")
                
                return SummaryReanalyzeResponse(
                    summary_id=result['id'],
                    is_new=False,
                    period_type=result['summary_type'],
                    period_date=result['summary_date'].isoformat(),
                    message="Summary marked for reanalysis",
                )
            
            else:
                # Update or create by period
                period_date = datetime.fromisoformat(request.period_date).date()
                
                result = await conn.fetchrow("""
                    INSERT INTO summaries (
                        city_id, summary_type, summary_date,
                        is_stale, status, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, true, 'pending', NOW(), NOW())
                    ON CONFLICT (city_id, summary_type, summary_date) DO UPDATE
                    SET is_stale = true, status = 'pending', updated_at = NOW()
                    RETURNING id, summary_type, summary_date, created_at
                """, request.city_id, request.summary_type, period_date)
                
                is_new = result['created_at'] == datetime.now()
                
                return SummaryReanalyzeResponse(
                    summary_id=result['id'],
                    is_new=is_new,
                    period_type=result['summary_type'],
                    period_date=result['summary_date'].isoformat(),
                    message=f"Summary {'created' if is_new else 'updated'} for reanalysis",
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reanalyzing summary: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


