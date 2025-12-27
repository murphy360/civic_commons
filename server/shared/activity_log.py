"""
Simple activity logging for services.

Logs events to the activity_log table for admin dashboard visibility.
This is a simplified version - see workers/scraper/pipeline/activity_logger.py
for the full-featured version used by the scraper.
"""

import json
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger("civic.activity")


class LogLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class LogCategory(str, Enum):
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    AI = "ai"


async def log_activity(
    pool,
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
    """Log an activity event to the database."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO activity_log 
                (level, category, action, message, entity_type, entity_id, 
                 entity_title, source_name, city_id, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                level.value,
                category.value,
                action,
                message,
                entity_type,
                entity_id,
                entity_title,
                source_name,
                city_id,
                json.dumps(details) if details else None,
            )
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")


async def log_service_started(pool, service_name: str) -> None:
    """Log that a service has started."""
    await log_activity(
        pool,
        LogLevel.SUCCESS,
        LogCategory.SYSTEM,
        "startup",
        f"{service_name} - Service started",
    )


async def log_service_stopped(pool, service_name: str) -> None:
    """Log that a service has stopped."""
    await log_activity(
        pool,
        LogLevel.INFO,
        LogCategory.SYSTEM,
        "shutdown",
        f"{service_name} - Service stopped",
    )
