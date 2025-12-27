"""
Centralized Activity Logger Client (HTTP)

A drop-in replacement for the direct-DB ActivityLogger that sends
activity logs to the centralized API endpoint instead.

Usage:
    logger = ActivityLoggerHTTP("http://commons-api:8080")
    await logger.log_download_started(doc_id, title, source_name)
    await logger.log_ai_completed(doc_id, title, model)
"""

import logging
import os
from typing import Optional
from enum import Enum

import httpx

logger = logging.getLogger("civic.activity")

# Default to internal Docker network URL
INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://commons-api:8080")


class LogLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class LogCategory(str, Enum):
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


class ActivityLoggerHTTP:
    """
    HTTP-based activity logger that sends events to the centralized API.
    
    This is a drop-in replacement for ActivityLogger that uses HTTP
    instead of direct database writes.
    """

    def __init__(self, api_url: Optional[str] = None):
        self._api_url = api_url or INTERNAL_API_URL
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def log(
        self,
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
            client = await self._get_client()
            
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
            
            response = await client.post(
                f"{self._api_url}/internal/log",
                json=payload,
            )
            
            if response.status_code != 200:
                logger.warning(f"Activity log API returned {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Failed to log activity via API: {e}")

    # =========================================================================
    # DOWNLOAD EVENTS
    # =========================================================================

    async def log_download_started(
        self,
        doc_id: int,
        title: str,
        source_name: Optional[str] = None,
        city_id: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.DOWNLOAD, "started",
            f"Download started: {title[:80]}...",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, city_id=city_id,
            details={"url": url} if url else None,
        )

    async def log_download_completed(
        self,
        doc_id: int,
        title: str,
        file_size: Optional[int] = None,
        source_name: Optional[str] = None,
        city_id: Optional[str] = None,
    ) -> None:
        size_str = f" ({file_size:,} bytes)" if file_size else ""
        await self.log(
            LogLevel.SUCCESS, LogCategory.DOWNLOAD, "completed",
            f"Download completed: {title[:80]}...{size_str}",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, city_id=city_id,
            details={"file_size": file_size} if file_size else None,
        )

    async def log_download_failed(
        self,
        doc_id: int,
        title: str,
        error: str,
        source_name: Optional[str] = None,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR, LogCategory.DOWNLOAD, "failed",
            f"Download failed: {title[:60]}... - {error[:100]}",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, city_id=city_id,
            details={"error": error},
        )

    async def log_download_skipped(
        self,
        doc_id: int,
        title: str,
        reason: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.DOWNLOAD, "skipped",
            f"Download skipped: {title[:60]}... - {reason}",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, details={"reason": reason},
        )

    # =========================================================================
    # EXTRACTION EVENTS
    # =========================================================================

    async def log_extraction_started(
        self, doc_id: int, title: str, source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.EXTRACTION, "started",
            f"Text extraction started: {title[:80]}...",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name,
        )

    async def log_extraction_completed(
        self, doc_id: int, title: str, char_count: Optional[int] = None,
        source_name: Optional[str] = None,
    ) -> None:
        chars_str = f" ({char_count:,} chars)" if char_count else ""
        await self.log(
            LogLevel.SUCCESS, LogCategory.EXTRACTION, "completed",
            f"Text extraction completed: {title[:80]}...{chars_str}",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name,
            details={"char_count": char_count} if char_count else None,
        )

    async def log_extraction_failed(
        self, doc_id: int, title: str, error: str, source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR, LogCategory.EXTRACTION, "failed",
            f"Text extraction failed: {title[:60]}... - {error[:100]}",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, details={"error": error},
        )

    # =========================================================================
    # AI EVENTS
    # =========================================================================

    async def log_ai_started(
        self, doc_id: int, title: str, model: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> None:
        model_str = f" using {model}" if model else ""
        await self.log(
            LogLevel.INFO, LogCategory.AI, "started",
            f"AI analysis started{model_str}: {title[:70]}...",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, details={"model": model} if model else None,
        )

    async def log_ai_completed(
        self, doc_id: int, title: str, model: Optional[str] = None,
        source_name: Optional[str] = None, summary_length: Optional[int] = None,
    ) -> None:
        model_str = f" using {model}" if model else ""
        await self.log(
            LogLevel.SUCCESS, LogCategory.AI, "completed",
            f"AI analysis completed{model_str}: {title[:70]}...",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name,
            details={"model": model, "summary_length": summary_length} if model or summary_length else None,
        )

    async def log_ai_failed(
        self, doc_id: int, title: str, error: str, model: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR, LogCategory.AI, "failed",
            f"AI analysis failed: {title[:60]}... - {error[:100]}",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, details={"error": error, "model": model},
        )

    async def log_ai_queued(
        self, doc_id: int, title: str, source_name: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.AI, "queued",
            f"AI analysis queued: {title[:80]}...",
            entity_type="document", entity_id=doc_id, entity_title=title,
            source_name=source_name, details={"reason": reason} if reason else None,
        )

    # =========================================================================
    # SCRAPE EVENTS
    # =========================================================================

    async def log_scrape_started(
        self, source_id: int, source_name: str, city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.SCRAPE, "started",
            f"Scrape started: {source_name}",
            entity_type="source", entity_id=source_id, entity_title=source_name,
            source_name=source_name, city_id=city_id,
        )

    async def log_scrape_completed(
        self, source_id: int, source_name: str, events_found: int = 0,
        documents_found: int = 0, city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.SUCCESS, LogCategory.SCRAPE, "completed",
            f"Scrape completed: {source_name} ({events_found} events, {documents_found} docs)",
            entity_type="source", entity_id=source_id, entity_title=source_name,
            source_name=source_name, city_id=city_id,
            details={"events_found": events_found, "documents_found": documents_found},
        )

    async def log_scrape_failed(
        self, source_id: int, source_name: str, error: str, city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR, LogCategory.SCRAPE, "failed",
            f"Scrape failed: {source_name} - {error[:100]}",
            entity_type="source", entity_id=source_id, entity_title=source_name,
            source_name=source_name, city_id=city_id, details={"error": error},
        )

    # =========================================================================
    # EVENT EVENTS
    # =========================================================================

    async def log_event_created(
        self, event_id: int, title: str, source_name: Optional[str] = None,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.SUCCESS, LogCategory.EVENT, "created",
            f"Event created: {title[:80]}...",
            entity_type="event", entity_id=event_id, entity_title=title,
            source_name=source_name, city_id=city_id,
        )

    async def log_event_updated(
        self, event_id: int, title: str, source_name: Optional[str] = None,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.EVENT, "updated",
            f"Event updated: {title[:80]}...",
            entity_type="event", entity_id=event_id, entity_title=title,
            source_name=source_name, city_id=city_id,
        )

    async def log_event_linked(
        self, event_id: int, event_title: str, doc_id: int, doc_title: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.SUCCESS, LogCategory.LINKING, "linked",
            f"Linked document to event: {doc_title[:40]}... → {event_title[:40]}...",
            entity_type="event", entity_id=event_id, entity_title=event_title,
            source_name=source_name, details={"doc_id": doc_id, "doc_title": doc_title},
        )

    # =========================================================================
    # SYSTEM EVENTS
    # =========================================================================

    async def log_system_started(self, service_name: str = "SCRAPER") -> None:
        await self.log(
            LogLevel.INFO, LogCategory.SYSTEM, "started",
            f"{service_name} service started",
            entity_type="service", entity_title=service_name,
        )

    async def log_system_stopped(self, service_name: str = "SCRAPER") -> None:
        await self.log(
            LogLevel.INFO, LogCategory.SYSTEM, "stopped",
            f"{service_name} service stopped",
            entity_type="service", entity_title=service_name,
        )

    async def log_system_error(
        self, message: str, error: Optional[str] = None, service_name: str = "SCRAPER",
    ) -> None:
        await self.log(
            LogLevel.ERROR, LogCategory.SYSTEM, "error", message,
            entity_type="service", entity_title=service_name,
            details={"error": error} if error else None,
        )

    # =========================================================================
    # SUMMARY EVENTS
    # =========================================================================

    async def log_summary_started(
        self, summary_id: int, title: str, summary_type: str = "weekly",
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.SUMMARY, "started",
            f"Generating {summary_type} summary: {title[:80]}...",
            entity_type="summary", entity_id=summary_id, entity_title=title,
            details={"summary_type": summary_type},
        )

    async def log_summary_completed(
        self, summary_id: int, title: str, summary_type: str = "weekly",
        doc_count: Optional[int] = None,
    ) -> None:
        docs_str = f" ({doc_count} documents)" if doc_count else ""
        await self.log(
            LogLevel.SUCCESS, LogCategory.SUMMARY, "completed",
            f"Generated {summary_type} summary{docs_str}: {title[:70]}...",
            entity_type="summary", entity_id=summary_id, entity_title=title,
            details={"summary_type": summary_type, "doc_count": doc_count},
        )

    async def log_summary_failed(
        self, summary_id: int, title: str, error: str, summary_type: str = "weekly",
    ) -> None:
        await self.log(
            LogLevel.ERROR, LogCategory.SUMMARY, "failed",
            f"Failed to generate {summary_type} summary: {error[:100]}",
            entity_type="summary", entity_id=summary_id, entity_title=title,
            details={"summary_type": summary_type, "error": error},
        )

    async def log_summary_queued(
        self, summary_id: int, title: str, summary_type: str = "weekly",
        reason: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO, LogCategory.SUMMARY, "queued",
            f"Queued {summary_type} summary for regeneration: {title[:70]}...",
            entity_type="summary", entity_id=summary_id, entity_title=title,
            details={"summary_type": summary_type, "reason": reason} if reason else {"summary_type": summary_type},
        )

    # =========================================================================
    # GENERIC ERROR
    # =========================================================================

    async def log_error(
        self, category: LogCategory, message: str, error: Optional[str] = None,
        entity_type: Optional[str] = None, entity_id: Optional[int] = None,
        entity_title: Optional[str] = None, source_name: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        full_details = details or {}
        if error:
            full_details["error"] = error
        await self.log(
            LogLevel.ERROR, category, "error", message,
            entity_type=entity_type, entity_id=entity_id, entity_title=entity_title,
            source_name=source_name, details=full_details if full_details else None,
        )


# Alias for backward compatibility - the HTTP logger can use the same name
ActivityLogger = ActivityLoggerHTTP


def create_activity_logger(api_url: Optional[str] = None) -> ActivityLoggerHTTP:
    """Create an activity logger with the centralized API URL."""
    return ActivityLoggerHTTP(api_url or INTERNAL_API_URL)
