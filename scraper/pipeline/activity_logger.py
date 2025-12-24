"""
Purpose: Activity logging for admin dashboard
Dependencies: asyncpg for PostgreSQL async access
Consumed by: worker pipeline components
Side effects: Writes to activity_log table
"""

import logging
import json
from datetime import datetime
from typing import Optional, Any
from enum import Enum

import asyncpg

logger = logging.getLogger("civic.activity")


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


class ActivityLogger:
    """
    Logs activity events to the database for the admin dashboard.
    
    Usage:
        activity = ActivityLogger(pool)
        await activity.log_download_started(doc_id, title, source_name)
        await activity.log_download_completed(doc_id, title, file_size)
        await activity.log_error(category, message, details)
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

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
        """
        Log an activity event to the database.
        
        Args:
            level: Log level (info, success, warning, error)
            category: Event category (download, ai, scrape, etc.)
            action: Action performed (started, completed, failed, etc.)
            message: Human-readable message
            entity_type: Type of entity (document, event, source, summary)
            entity_id: ID of the entity
            entity_title: Title/name of the entity
            source_name: Name of the data source
            city_id: City identifier
            details: Additional JSON details
        """
        try:
            async with self._pool.acquire() as conn:
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
            # Don't let logging failures break the pipeline
            logger.error(f"Failed to log activity: {e}")

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
            LogLevel.INFO,
            LogCategory.DOWNLOAD,
            "started",
            f"Download started: {title[:80]}...",
            entity_type="document",
            entity_id=doc_id,
            entity_title=title,
            source_name=source_name,
            city_id=city_id,
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
            LogLevel.SUCCESS,
            LogCategory.DOWNLOAD,
            "completed",
            f"Download completed: {title[:80]}...{size_str}",
            entity_type="document",
            entity_id=doc_id,
            entity_title=title,
            source_name=source_name,
            city_id=city_id,
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
            LogLevel.ERROR,
            LogCategory.DOWNLOAD,
            "failed",
            f"Download failed: {title[:60]}... - {error[:100]}",
            entity_type="document",
            entity_id=doc_id,
            entity_title=title,
            source_name=source_name,
            city_id=city_id,
            details={"error": error},
        )

    # =========================================================================
    # EXTRACTION EVENTS
    # =========================================================================

    async def log_extraction_started(
        self,
        doc_id: int,
        title: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO,
            LogCategory.EXTRACTION,
            "started",
            f"Text extraction started: {title[:80]}...",
            entity_type="document",
            entity_id=doc_id,
            entity_title=title,
            source_name=source_name,
        )

    async def log_extraction_completed(
        self,
        doc_id: int,
        title: str,
        char_count: Optional[int] = None,
        source_name: Optional[str] = None,
    ) -> None:
        chars_str = f" ({char_count:,} chars)" if char_count else ""
        await self.log(
            LogLevel.SUCCESS,
            LogCategory.EXTRACTION,
            "completed",
            f"Text extraction completed: {title[:80]}...{chars_str}",
            entity_type="document",
            entity_id=doc_id,
            entity_title=title,
            source_name=source_name,
            details={"char_count": char_count} if char_count else None,
        )

    async def log_extraction_failed(
        self,
        doc_id: int,
        title: str,
        error: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR,
            LogCategory.EXTRACTION,
            "failed",
            f"Text extraction failed: {title[:60]}... - {error[:100]}",
            entity_type="document",
            entity_id=doc_id,
            entity_title=title,
            source_name=source_name,
            details={"error": error},
        )

    # =========================================================================
    # AI PROCESSING EVENTS
    # =========================================================================

    async def log_ai_started(
        self,
        entity_type: str,
        entity_id: int,
        title: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO,
            LogCategory.AI,
            "started",
            f"AI analysis started: {title[:80]}...",
            entity_type=entity_type,
            entity_id=entity_id,
            entity_title=title,
            source_name=source_name,
        )

    async def log_ai_completed(
        self,
        entity_type: str,
        entity_id: int,
        title: str,
        summary_length: Optional[int] = None,
        model_used: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> None:
        length_str = f" ({summary_length:,} chars)" if summary_length else ""
        await self.log(
            LogLevel.SUCCESS,
            LogCategory.AI,
            "completed",
            f"AI analysis completed: {title[:80]}...{length_str}",
            entity_type=entity_type,
            entity_id=entity_id,
            entity_title=title,
            source_name=source_name,
            details={
                "summary_length": summary_length,
                "model_used": model_used,
            },
        )

    async def log_ai_failed(
        self,
        entity_type: str,
        entity_id: int,
        title: str,
        error: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR,
            LogCategory.AI,
            "failed",
            f"AI analysis failed: {title[:60]}... - {error[:100]}",
            entity_type=entity_type,
            entity_id=entity_id,
            entity_title=title,
            source_name=source_name,
            details={"error": error},
        )

    async def log_ai_queued(
        self,
        entity_type: str,
        entity_id: int,
        title: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO,
            LogCategory.AI,
            "queued",
            f"Queued for AI analysis: {title[:80]}...",
            entity_type=entity_type,
            entity_id=entity_id,
            entity_title=title,
            source_name=source_name,
        )

    # =========================================================================
    # SCRAPING EVENTS
    # =========================================================================

    async def log_scrape_started(
        self,
        source_id: int,
        source_name: str,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO,
            LogCategory.SCRAPE,
            "started",
            f"Scrape started: {source_name}",
            entity_type="source",
            entity_id=source_id,
            entity_title=source_name,
            source_name=source_name,
            city_id=city_id,
        )

    async def log_scrape_completed(
        self,
        source_id: int,
        source_name: str,
        events_found: int = 0,
        documents_found: int = 0,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.SUCCESS,
            LogCategory.SCRAPE,
            "completed",
            f"Scrape completed: {source_name} - {events_found} events, {documents_found} documents",
            entity_type="source",
            entity_id=source_id,
            entity_title=source_name,
            source_name=source_name,
            city_id=city_id,
            details={
                "events_found": events_found,
                "documents_found": documents_found,
            },
        )

    async def log_scrape_failed(
        self,
        source_id: int,
        source_name: str,
        error: str,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR,
            LogCategory.SCRAPE,
            "failed",
            f"Scrape failed: {source_name} - {error[:100]}",
            entity_type="source",
            entity_id=source_id,
            entity_title=source_name,
            source_name=source_name,
            city_id=city_id,
            details={"error": error},
        )

    # =========================================================================
    # DOCUMENT DISCOVERY EVENTS
    # =========================================================================

    async def log_document_discovered(
        self,
        doc_id: int,
        title: str,
        doc_type: str,
        source_name: Optional[str] = None,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.INFO,
            LogCategory.SCRAPE,
            "discovered",
            f"New document discovered: {title[:80]}... ({doc_type})",
            entity_type="document",
            entity_id=doc_id,
            entity_title=title,
            source_name=source_name,
            city_id=city_id,
            details={"document_type": doc_type},
        )

    async def log_event_discovered(
        self,
        event_id: int,
        title: str,
        start_time: Optional[datetime] = None,
        source_name: Optional[str] = None,
        city_id: Optional[str] = None,
    ) -> None:
        time_str = f" on {start_time.strftime('%Y-%m-%d')}" if start_time else ""
        await self.log(
            LogLevel.INFO,
            LogCategory.EVENT,
            "discovered",
            f"New event discovered: {title[:80]}...{time_str}",
            entity_type="event",
            entity_id=event_id,
            entity_title=title,
            source_name=source_name,
            city_id=city_id,
            details={"start_time": start_time.isoformat() if start_time else None},
        )

    # =========================================================================
    # LINKING EVENTS
    # =========================================================================

    async def log_document_linked(
        self,
        doc_id: int,
        doc_title: str,
        event_id: int,
        event_title: str,
        source_name: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.SUCCESS,
            LogCategory.LINKING,
            "linked",
            f"Document linked to event: {doc_title[:40]}... → {event_title[:40]}...",
            entity_type="document",
            entity_id=doc_id,
            entity_title=doc_title,
            source_name=source_name,
            details={"event_id": event_id, "event_title": event_title},
        )

    # =========================================================================
    # SYSTEM EVENTS
    # =========================================================================

    async def log_system_started(self) -> None:
        await self.log(
            LogLevel.INFO,
            LogCategory.SYSTEM,
            "started",
            "Worker service started",
        )

    async def log_system_stopped(self) -> None:
        await self.log(
            LogLevel.INFO,
            LogCategory.SYSTEM,
            "stopped",
            "Worker service stopped",
        )

    async def log_system_error(self, error: str, details: Optional[dict] = None) -> None:
        await self.log(
            LogLevel.ERROR,
            LogCategory.SYSTEM,
            "error",
            f"System error: {error[:200]}",
            details={"error": error, **(details or {})},
        )

    # =========================================================================
    # SUMMARY GENERATION EVENTS
    # =========================================================================

    async def log_summary_started(
        self,
        summary_type: str,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
        city_id: Optional[str] = None,
    ) -> None:
        period_str = ""
        if period_start and period_end:
            period_str = f" ({period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')})"
        await self.log(
            LogLevel.INFO,
            LogCategory.SUMMARY,
            "started",
            f"{summary_type.capitalize()} summary generation started{period_str}",
            entity_type="summary",
            city_id=city_id,
            details={
                "summary_type": summary_type,
                "period_start": period_start.isoformat() if period_start else None,
                "period_end": period_end.isoformat() if period_end else None,
            },
        )

    async def log_summary_completed(
        self,
        summary_id: int,
        summary_type: str,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.SUCCESS,
            LogCategory.SUMMARY,
            "completed",
            f"{summary_type.capitalize()} summary generated successfully",
            entity_type="summary",
            entity_id=summary_id,
            city_id=city_id,
            details={"summary_type": summary_type},
        )

    async def log_summary_failed(
        self,
        summary_type: str,
        error: str,
        city_id: Optional[str] = None,
    ) -> None:
        await self.log(
            LogLevel.ERROR,
            LogCategory.SUMMARY,
            "failed",
            f"{summary_type.capitalize()} summary generation failed: {error[:100]}",
            entity_type="summary",
            city_id=city_id,
            details={"summary_type": summary_type, "error": error},
        )
