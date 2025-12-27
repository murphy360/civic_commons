"""
Simple HTTP-based activity logging for services.

Logs events via the centralized activity API endpoint.
This replaces direct database logging in services.
"""

import logging
import os
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger("civic.activity")

# Internal API URL for centralized activity logging
INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://commons-api:8080")

# Shared HTTP client (initialized lazily)
_http_client: Optional[httpx.AsyncClient] = None


class LogLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class LogCategory(str, Enum):
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    AI = "ai"
    DOWNLOAD = "download"
    EXTRACTION = "extraction"
    SCRAPE = "scrape"
    EVENT = "event"
    LINKING = "linking"
    SUMMARY = "summary"
    USER_ACTION = "user_action"


async def _get_client() -> httpx.AsyncClient:
    """Get or create the HTTP client."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=10.0)
    return _http_client


async def close_client() -> None:
    """Close the HTTP client."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


async def log_activity(
    level: LogLevel,
    category: LogCategory,
    action: str,
    message: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    entity_title: Optional[str] = None,
    source_name: Optional[str] = None,
    city_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Log an activity event via the centralized API."""
    try:
        client = await _get_client()
        
        payload = {
            "level": level.value if isinstance(level, LogLevel) else level,
            "category": category.value if isinstance(category, LogCategory) else category,
            "action": action,
            "message": message,
        }
        
        if entity_type:
            payload["entity_type"] = entity_type
        if entity_id is not None:
            payload["entity_id"] = entity_id
        if entity_title:
            payload["entity_title"] = entity_title
        if source_name:
            payload["source_name"] = source_name
        if city_id:
            payload["city_id"] = city_id
        if details:
            payload["details"] = details
        
        await client.post(
            f"{INTERNAL_API_URL}/internal/log",
            json=payload,
        )
    except Exception as e:
        logger.error(f"Failed to log activity via API: {e}")


async def log_service_started(service_name: str) -> None:
    """Log that a service has started."""
    await log_activity(
        LogLevel.SUCCESS,
        LogCategory.SYSTEM,
        "startup",
        f"{service_name} - Service started",
    )


async def log_service_stopped(service_name: str) -> None:
    """Log that a service has stopped."""
    await log_activity(
        LogLevel.INFO,
        LogCategory.SYSTEM,
        "shutdown",
        f"{service_name} - Service stopped",
    )


async def log_tool_call(
    tool_name: str,
    success: bool = True,
    error: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Log a tool call for admin visibility."""
    level = LogLevel.SUCCESS if success else LogLevel.ERROR
    action = "executed" if success else "failed"
    message = f"Tool {tool_name} {action}"
    if error:
        message = f"Tool {tool_name} failed: {error}"
    
    await log_activity(
        level,
        LogCategory.TOOL_CALL,
        action,
        message,
        details=details,
    )
