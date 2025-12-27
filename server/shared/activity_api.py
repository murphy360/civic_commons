"""
Centralized Activity Logging API

Provides a single internal endpoint for all services to log activity events
to the activity_log table. This replaces direct database logging from
individual services.

Usage:
    POST /internal/log
    {
        "level": "info",
        "category": "ai", 
        "action": "summary_queued",
        "message": "Manual re-analysis requested",
        "entity_type": "summary",
        "entity_id": 123,
        "entity_title": "weekly summary",
        "city_id": "twinsburg_oh",
        "details": {"triggered_by": "user"}
    }

This endpoint is internal-only (accessible via Docker network).
"""

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("civic_commons.activity_api")

# Create router for activity logging endpoints
router = APIRouter(prefix="/internal", tags=["internal"])


class LogLevel:
    """Valid log levels."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    
    ALL = {INFO, SUCCESS, WARNING, ERROR}


class LogCategory:
    """Valid log categories."""
    DOWNLOAD = "download"
    EXTRACTION = "extraction"
    AI = "ai"
    SCRAPE = "scrape"
    SYSTEM = "system"
    EVENT = "event"
    LINKING = "linking"
    SUMMARY = "summary"
    TOOL_CALL = "tool_call"
    USER_ACTION = "user_action"
    
    ALL = {DOWNLOAD, EXTRACTION, AI, SCRAPE, SYSTEM, EVENT, LINKING, SUMMARY, TOOL_CALL, USER_ACTION}


class ActivityLogRequest(BaseModel):
    """Request body for logging an activity event."""
    level: str
    category: str
    action: str
    message: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    entity_title: Optional[str] = None
    source_name: Optional[str] = None
    city_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class ActivityLogResponse(BaseModel):
    """Response from logging an activity event."""
    success: bool
    log_id: Optional[int] = None
    error: Optional[str] = None


# Database pool will be injected from main app
_db_pool = None


def set_db_pool(pool):
    """Set the database pool for logging."""
    global _db_pool
    _db_pool = pool


@router.post("/log", response_model=ActivityLogResponse)
async def log_activity(request: ActivityLogRequest) -> ActivityLogResponse:
    """
    Log an activity event to the database.
    
    This is an internal endpoint for use by all Civic Commons services.
    It should only be accessible via the Docker internal network.
    """
    global _db_pool
    
    if _db_pool is None:
        logger.error("Database pool not initialized")
        raise HTTPException(status_code=503, detail="Database not available")
    
    # Validate level
    if request.level not in LogLevel.ALL:
        return ActivityLogResponse(
            success=False,
            error=f"Invalid level: {request.level}. Must be one of: {LogLevel.ALL}"
        )
    
    # Validate category  
    if request.category not in LogCategory.ALL:
        return ActivityLogResponse(
            success=False,
            error=f"Invalid category: {request.category}. Must be one of: {LogCategory.ALL}"
        )
    
    try:
        async with _db_pool.acquire() as conn:
            log_id = await conn.fetchval("""
                INSERT INTO activity_log (
                    level, category, action, message,
                    entity_type, entity_id, entity_title,
                    source_name, city_id, details
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
            """,
                request.level,
                request.category,
                request.action,
                request.message,
                request.entity_type,
                request.entity_id,
                request.entity_title,
                request.source_name,
                request.city_id,
                json.dumps(request.details) if request.details else None,
            )
        
        logger.debug(f"Logged activity: {request.category}/{request.action} - {request.message}")
        
        return ActivityLogResponse(success=True, log_id=log_id)
        
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")
        return ActivityLogResponse(success=False, error=str(e))
