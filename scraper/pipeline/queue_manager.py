"""
Purpose: Unified queue manager for all content lifecycle stages
Dependencies: asyncpg for database operations
Consumed by: main.py, API endpoints, admin dashboard
Side effects: Updates queue status in database

The QueueManager tracks content through its entire lifecycle:
  1. DISCOVERED - Scraper found it, metadata stored, visible in UI as placeholder
  2. DOWNLOAD_PENDING - Queued for download (prioritized by date)
  3. DOWNLOADING - Currently being downloaded
  4. DOWNLOADED - File saved locally, ready for extraction
  5. EXTRACTION_PENDING - Queued for text extraction
  6. EXTRACTING - Currently extracting text/content
  7. EXTRACTED - Text available, ready for AI analysis  
  8. AI_PENDING - Queued for AI summary generation
  9. AI_PROCESSING - AI is generating summary
  10. COMPLETE - Fully processed
  11. FAILED - Processing failed (with error details)

Priority is always: most recent date first (including future dates)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Any

logger = logging.getLogger("civic.queue_manager")


class ContentStatus(str, Enum):
    """Content lifecycle status - tracks where each item is in processing."""
    # Discovery phase
    DISCOVERED = "discovered"           # Found by scraper, metadata only
    
    # Download phase
    DOWNLOAD_PENDING = "download_pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    
    # Extraction phase (PDF → text)
    EXTRACTION_PENDING = "extraction_pending"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    
    # AI Analysis phase
    AI_PENDING = "ai_pending"
    AI_PROCESSING = "ai_processing"
    
    # Terminal states
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"                 # Non-processable (e.g., image-only PDF)


class ContentType(str, Enum):
    """Types of content that flow through the queue."""
    DOCUMENT = "document"       # PDFs, agendas, minutes, packets
    VIDEO = "video"             # YouTube, Vimeo recordings
    EVENT = "event"             # Calendar events (for AI summary)
    SUMMARY = "summary"         # Period summaries (weekly, monthly, etc.)


@dataclass
class QueueItem:
    """A single item in the processing queue."""
    id: int
    content_type: ContentType
    status: ContentStatus
    title: str
    item_date: Optional[datetime]       # For priority ordering
    source_url: Optional[str]
    source_name: Optional[str]
    
    # Processing metadata
    error_message: Optional[str] = None
    retry_count: int = 0
    retry_after: Optional[datetime] = None
    
    # Progress tracking
    file_size_bytes: Optional[int] = None
    download_progress: Optional[float] = None  # 0.0 to 1.0
    
    # Timestamps
    discovered_at: Optional[datetime] = None
    download_started_at: Optional[datetime] = None
    download_completed_at: Optional[datetime] = None
    extraction_started_at: Optional[datetime] = None
    extraction_completed_at: Optional[datetime] = None
    ai_started_at: Optional[datetime] = None
    ai_completed_at: Optional[datetime] = None


@dataclass
class QueueStats:
    """Statistics for a queue stage."""
    pending: int = 0
    in_progress: int = 0
    completed_today: int = 0
    failed_today: int = 0
    oldest_pending_date: Optional[datetime] = None
    newest_pending_date: Optional[datetime] = None
    avg_processing_time_seconds: Optional[float] = None


@dataclass
class QueueStatus:
    """Complete status of all queues for UI display."""
    # Per-stage statistics
    download: QueueStats = field(default_factory=QueueStats)
    extraction: QueueStats = field(default_factory=QueueStats)
    ai_documents: QueueStats = field(default_factory=QueueStats)
    ai_events: QueueStats = field(default_factory=QueueStats)
    ai_summaries: QueueStats = field(default_factory=QueueStats)
    
    # Currently processing items
    active_downloads: list[QueueItem] = field(default_factory=list)
    active_extractions: list[QueueItem] = field(default_factory=list)
    active_ai: list[QueueItem] = field(default_factory=list)
    
    # Recent failures (for troubleshooting)
    recent_failures: list[QueueItem] = field(default_factory=list)
    
    # Overall health
    total_pending: int = 0
    total_in_progress: int = 0
    is_healthy: bool = True
    health_message: str = "All systems operational"
    
    # Timestamps
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass 
class QueueConfig:
    """Configuration for queue processing behavior."""
    # Download settings
    max_concurrent_downloads: int = 3
    download_timeout_seconds: int = 300
    download_retry_max: int = 3
    download_retry_delay_seconds: int = 60
    
    # Extraction settings
    max_concurrent_extractions: int = 2
    extraction_timeout_seconds: int = 120
    
    # AI settings
    max_concurrent_ai: int = 1
    ai_batch_size: int = 5
    ai_max_age_days: int = 365          # Don't process items older than this
    
    # Priority settings
    prioritize_future: bool = True      # Future dates get highest priority
    priority_window_days: int = 30      # Items within this window of today get boosted


class QueueManager:
    """
    Unified queue manager for content processing lifecycle.
    
    Responsibilities:
    - Track content from discovery through completion
    - Prioritize by date (most recent/upcoming first)
    - Expose queue status for UI consumption
    - Handle retries and failure tracking
    - Coordinate between processing stages
    """

    def __init__(self, db_pool, config: Optional[QueueConfig] = None):
        self.db_pool = db_pool
        self.config = config or QueueConfig()
        
    # =========================================================================
    # Content Discovery (called by scrapers)
    # =========================================================================
    
    async def register_discovered_document(
        self,
        conn,
        source_id: int,
        title: str,
        source_url: str,
        document_type: str,
        meeting_date: Optional[datetime] = None,
        external_id: Optional[str] = None,
        raw_data: Optional[dict] = None,
    ) -> int:
        """
        Register a newly discovered document. Creates a placeholder that's
        immediately visible in the UI, then queues it for download.
        
        Returns: document ID
        """
        # Check if document already exists
        existing = await conn.fetchval("""
            SELECT id FROM documents 
            WHERE source_id = $1 AND (
                (external_id IS NOT NULL AND external_id = $2)
                OR (source_url = $3)
            )
        """, source_id, external_id, source_url)
        
        if existing:
            logger.debug(f"Document already exists: {title}")
            return existing
        
        # Insert as discovered - immediately visible, queued for download
        doc_id = await conn.fetchval("""
            INSERT INTO documents (
                source_id, external_id, title, document_type, source_url,
                meeting_date, raw_data, content_status, discovered_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            RETURNING id
        """, source_id, external_id, title, document_type, source_url,
             meeting_date, raw_data, ContentStatus.DISCOVERED.value)
        
        logger.info(f"Discovered document: {title} (id={doc_id})")
        return doc_id
    
    async def register_discovered_video(
        self,
        conn,
        source_id: int,
        title: str,
        video_url: str,
        meeting_date: Optional[datetime] = None,
        external_id: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> int:
        """Register a discovered video. Videos skip download phase."""
        existing = await conn.fetchval("""
            SELECT id FROM documents 
            WHERE source_id = $1 AND (
                (external_id IS NOT NULL AND external_id = $2)
                OR (source_url = $3)
            )
        """, source_id, external_id, video_url)
        
        if existing:
            return existing
        
        # Videos go straight to AI_PENDING (no download/extraction needed)
        doc_id = await conn.fetchval("""
            INSERT INTO documents (
                source_id, external_id, title, document_type, source_url,
                meeting_date, content_status, discovered_at
            ) VALUES ($1, $2, $3, 'video', $4, $5, $6, NOW())
            RETURNING id
        """, source_id, external_id, title, video_url, meeting_date,
             ContentStatus.AI_PENDING.value)
        
        logger.info(f"Discovered video: {title} (id={doc_id})")
        return doc_id

    # =========================================================================
    # Queue Transitions
    # =========================================================================
    
    async def mark_download_pending(self, conn, doc_id: int) -> None:
        """Move document to download queue."""
        await conn.execute("""
            UPDATE documents SET content_status = $1, updated_at = NOW()
            WHERE id = $2
        """, ContentStatus.DOWNLOAD_PENDING.value, doc_id)
    
    async def mark_downloading(self, conn, doc_id: int) -> None:
        """Mark document as currently downloading."""
        await conn.execute("""
            UPDATE documents SET 
                content_status = $1, 
                download_started_at = NOW(),
                updated_at = NOW()
            WHERE id = $2
        """, ContentStatus.DOWNLOADING.value, doc_id)
    
    async def mark_downloaded(
        self, 
        conn, 
        doc_id: int,
        local_path: str,
        file_size_bytes: int,
        mime_type: str,
        file_hash: str,
    ) -> None:
        """Mark document as downloaded, queue for extraction."""
        await conn.execute("""
            UPDATE documents SET 
                content_status = $1,
                local_path = $2,
                file_size_bytes = $3,
                mime_type = $4,
                file_hash = $5,
                download_completed_at = NOW(),
                updated_at = NOW()
            WHERE id = $6
        """, ContentStatus.DOWNLOADED.value, local_path, file_size_bytes,
             mime_type, file_hash, doc_id)
    
    async def mark_extraction_pending(self, conn, doc_id: int) -> None:
        """Queue document for text extraction."""
        await conn.execute("""
            UPDATE documents SET content_status = $1, updated_at = NOW()
            WHERE id = $2
        """, ContentStatus.EXTRACTION_PENDING.value, doc_id)
    
    async def mark_extracting(self, conn, doc_id: int) -> None:
        """Mark document as currently being extracted."""
        await conn.execute("""
            UPDATE documents SET 
                content_status = $1,
                extraction_started_at = NOW(),
                updated_at = NOW()
            WHERE id = $2
        """, ContentStatus.EXTRACTING.value, doc_id)
    
    async def mark_extracted(
        self,
        conn,
        doc_id: int,
        content_text: Optional[str],
        content_markdown: Optional[str],
    ) -> None:
        """Mark document as extracted, queue for AI."""
        await conn.execute("""
            UPDATE documents SET 
                content_status = $1,
                content_text = $2,
                content_markdown = $3,
                extraction_completed_at = NOW(),
                updated_at = NOW()
            WHERE id = $4
        """, ContentStatus.EXTRACTED.value, content_text, content_markdown, doc_id)
    
    async def mark_ai_pending(self, conn, doc_id: int) -> None:
        """Queue document for AI analysis."""
        await conn.execute("""
            UPDATE documents SET content_status = $1, updated_at = NOW()
            WHERE id = $2
        """, ContentStatus.AI_PENDING.value, doc_id)
    
    async def mark_ai_processing(self, conn, doc_id: int) -> None:
        """Mark document as currently being processed by AI."""
        await conn.execute("""
            UPDATE documents SET 
                content_status = $1,
                ai_started_at = NOW(),
                updated_at = NOW()
            WHERE id = $2
        """, ContentStatus.AI_PROCESSING.value, doc_id)
    
    async def mark_complete(
        self,
        conn,
        doc_id: int,
        ai_summary: str,
        model_used: str,
    ) -> None:
        """Mark document as fully processed."""
        # For ordinance/resolution documents, extract legislation number from title if not already set
        doc = await conn.fetchrow("SELECT document_type, title, legislation_number FROM documents WHERE id = $1", doc_id)
        legislation_number = doc['legislation_number']
        
        if not legislation_number and doc['document_type'] in ('ordinance', 'resolution'):
            # Try to extract legislation number from title (e.g., "01-25" from "01-25: Twinsburg TIF Ordinance...")
            match = re.match(r'^(\d+-\d{2,4})', doc['title'].strip())
            if match:
                legislation_number = match.group(1)
        
        await conn.execute("""
            UPDATE documents SET 
                content_status = $1,
                ai_summary = $2,
                ai_model_used = $3,
                legislation_number = $4,
                ai_summary_updated_at = NOW(),
                ai_completed_at = NOW(),
                updated_at = NOW()
            WHERE id = $5
        """, ContentStatus.COMPLETE.value, ai_summary, model_used, legislation_number, doc_id)
    
    async def mark_failed(
        self,
        conn,
        doc_id: int,
        error_message: str,
        increment_retry: bool = True,
    ) -> None:
        """Mark document as failed with error details."""
        if increment_retry:
            await conn.execute("""
                UPDATE documents SET 
                    content_status = $1,
                    error_message = $2,
                    retry_count = COALESCE(retry_count, 0) + 1,
                    retry_after = NOW() + INTERVAL '1 minute' * POWER(2, COALESCE(retry_count, 0)),
                    updated_at = NOW()
                WHERE id = $3
            """, ContentStatus.FAILED.value, error_message, doc_id)
        else:
            await conn.execute("""
                UPDATE documents SET 
                    content_status = $1,
                    error_message = $2,
                    updated_at = NOW()
                WHERE id = $3
            """, ContentStatus.FAILED.value, error_message, doc_id)
    
    async def mark_skipped(self, conn, doc_id: int, reason: str) -> None:
        """Mark document as skipped (non-processable)."""
        await conn.execute("""
            UPDATE documents SET 
                content_status = $1,
                error_message = $2,
                updated_at = NOW()
            WHERE id = $3
        """, ContentStatus.SKIPPED.value, reason, doc_id)

    # =========================================================================
    # Queue Retrieval (for processors)
    # =========================================================================
    
    async def get_download_queue(
        self,
        conn,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get documents pending download, prioritized by date.
        Most recent (including future) first.
        """
        return await conn.fetch("""
            SELECT 
                d.id, d.title, d.document_type, d.source_url, d.meeting_date,
                d.retry_count, s.name as source_name
            FROM documents d
            JOIN sources s ON d.source_id = s.id
            WHERE d.content_status IN ($1, $2)
              AND (d.retry_after IS NULL OR d.retry_after <= NOW())
              AND d.source_url IS NOT NULL
            ORDER BY 
                -- Future dates first, then most recent past
                CASE WHEN d.meeting_date >= CURRENT_DATE THEN 0 ELSE 1 END,
                ABS(EXTRACT(EPOCH FROM (d.meeting_date - CURRENT_TIMESTAMP))),
                d.created_at DESC
            LIMIT $3
        """, ContentStatus.DISCOVERED.value, ContentStatus.DOWNLOAD_PENDING.value, limit)
    
    async def get_extraction_queue(
        self,
        conn,
        limit: int = 10,
    ) -> list[dict]:
        """Get documents pending text extraction."""
        return await conn.fetch("""
            SELECT 
                d.id, d.title, d.document_type, d.local_path, d.mime_type,
                d.meeting_date, s.name as source_name
            FROM documents d
            JOIN sources s ON d.source_id = s.id
            WHERE d.content_status IN ($1, $2)
              AND d.local_path IS NOT NULL
            ORDER BY 
                CASE WHEN d.meeting_date >= CURRENT_DATE THEN 0 ELSE 1 END,
                ABS(EXTRACT(EPOCH FROM (d.meeting_date - CURRENT_TIMESTAMP))),
                d.created_at DESC
            LIMIT $3
        """, ContentStatus.DOWNLOADED.value, ContentStatus.EXTRACTION_PENDING.value, limit)
    
    async def get_ai_queue(
        self,
        conn,
        limit: int = 10,
        max_age_days: int = 365,
    ) -> list[dict]:
        """
        Get unified AI queue - documents, videos, events, summaries
        with proper dependency ordering:
        
        1. Documents & Videos FIRST (no dependencies)
        2. Events ONLY when all linked documents have AI summaries
        3. Periodic summaries ONLY when events in period are summarized
        
        Within each tier, sorted by date priority (future first, then most recent).
        """
        effective_max_age = max_age_days if max_age_days > 0 else 36500
        
        return await conn.fetch("""
            SELECT * FROM (
                -- TIER 1: Documents ready for AI (highest priority)
                SELECT 
                    id,
                    'document'::text as item_type,
                    title,
                    document_type,
                    NULL::varchar as summary_type,
                    COALESCE(meeting_date, created_at) as item_date,
                    content_markdown,
                    local_path,
                    source_url,
                    1 as priority_tier,
                    COALESCE(retry_count, 0) as retry_count,
                    summary_priority
                FROM documents
                WHERE content_status IN ($1, $2)
                  AND content_markdown IS NOT NULL
                  AND document_type != 'video'
                  AND COALESCE(retry_count, 0) < 3  -- Exclude docs that have failed 3+ times
                  AND COALESCE(meeting_date, created_at) >= NOW() - INTERVAL '1 day' * $4
                
                UNION ALL
                
                -- TIER 1: Videos ready for AI (same priority as documents)
                SELECT 
                    id,
                    'video'::text as item_type,
                    title,
                    'video' as document_type,
                    NULL::varchar as summary_type,
                    COALESCE(meeting_date, created_at) as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    source_url,
                    1 as priority_tier,
                    COALESCE(retry_count, 0) as retry_count,
                    summary_priority
                FROM documents
                WHERE content_status = $3
                  AND document_type = 'video'
                  AND source_url LIKE '%youtu%'
                  AND COALESCE(retry_count, 0) < 3  -- Exclude videos that have failed 3+ times
                  AND COALESCE(meeting_date, created_at) >= NOW() - INTERVAL '1 day' * $4
                
                UNION ALL
                
                -- TIER 2: Events where ALL linked documents have AI summaries
                SELECT 
                    e.id,
                    'event'::text as item_type,
                    e.title,
                    NULL as document_type,
                    NULL::varchar as summary_type,
                    COALESCE(e.start_time, e.created_at) as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    2 as priority_tier,
                    0 as retry_count,
                    e.summary_priority
                FROM events e
                WHERE (e.ai_summary IS NULL OR e.ai_summary = '')
                  AND COALESCE(e.start_time, e.created_at) >= NOW() - INTERVAL '1 day' * $4
                  -- Only include if ALL linked documents are complete
                  AND NOT EXISTS (
                      SELECT 1 FROM event_documents ed
                      JOIN documents d ON ed.document_id = d.id
                      WHERE ed.event_id = e.id
                        AND (d.ai_summary IS NULL OR d.ai_summary = '')
                        AND d.content_status NOT IN ('skipped', 'failed')
                  )
                  -- Must have at least one linked document with a summary
                  AND EXISTS (
                      SELECT 1 FROM event_documents ed
                      JOIN documents d ON ed.document_id = d.id
                      WHERE ed.event_id = e.id
                        AND d.ai_summary IS NOT NULL
                        AND d.ai_summary != ''
                        AND d.ai_summary != '[AI_SUMMARY_FAILED]'
                  )
                
                UNION ALL
                
                -- TIER 3: Periodic summaries where events in period are summarized
                SELECT 
                    s.id,
                    'summary'::text as item_type,
                    COALESCE(s.title, s.summary_type || ' Summary') as title,
                    NULL as document_type,
                    s.summary_type,
                    s.period_end as item_date,
                    NULL as content_markdown,
                    NULL as local_path,
                    NULL as source_url,
                    3 as priority_tier,
                    0 as retry_count,
                    NULL::timestamp as summary_priority
                FROM summaries s
                WHERE s.status IN ('pending', 'stale')
                  AND s.period_end >= NOW() - INTERVAL '1 day' * $4
                  -- Only include if there are summarized events in this period
                  AND EXISTS (
                      SELECT 1 FROM events e
                      WHERE e.start_time >= s.period_start
                        AND e.start_time < s.period_end
                        AND e.ai_summary IS NOT NULL
                        AND e.ai_summary != ''
                  )
                  -- Exclude if there are unsummarized events that should be included
                  AND NOT EXISTS (
                      SELECT 1 FROM events e
                      WHERE e.start_time >= s.period_start
                        AND e.start_time < s.period_end
                        AND (e.ai_summary IS NULL OR e.ai_summary = '')
                        -- Only block if the event has documents that are summarized
                        -- (events with no docs or all skipped docs can be ignored)
                        AND EXISTS (
                            SELECT 1 FROM event_documents ed
                            JOIN documents d ON ed.document_id = d.id
                            WHERE ed.event_id = e.id
                              AND d.ai_summary IS NOT NULL
                        )
                  )
            ) AS unified_queue
            ORDER BY 
                -- HIGHEST PRIORITY: Manually queued items (summary_priority is set)
                CASE WHEN summary_priority IS NOT NULL THEN 0 ELSE 1 END,
                summary_priority DESC NULLS LAST,
                -- Process by tier: documents/videos first, then events, then summaries
                priority_tier,
                -- Within tier: items with no retries first, then retry 1, then retry 2
                retry_count,
                -- Within tier 1: PDFs before videos (to build up document summaries for events)
                CASE WHEN item_type = 'document' THEN 0 ELSE 1 END,
                -- Within tier: future dates first
                CASE WHEN item_date >= CURRENT_DATE THEN 0 ELSE 1 END,
                -- Then closest to today (past or future)
                ABS(EXTRACT(EPOCH FROM (item_date - CURRENT_TIMESTAMP))),
                -- Finally by date
                item_date DESC NULLS LAST
            LIMIT $5
        """, ContentStatus.EXTRACTED.value, ContentStatus.AI_PENDING.value,
             ContentStatus.AI_PENDING.value, effective_max_age, limit)

    # =========================================================================
    # Queue Status (for UI)
    # =========================================================================
    
    async def get_queue_status(self, conn) -> dict:
        """
        Get comprehensive queue status for UI display.
        Returns a dict that can be directly JSON serialized.
        """
        # Download queue stats
        download_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE content_status IN ('discovered', 'download_pending')) as pending,
                COUNT(*) FILTER (WHERE content_status = 'downloading') as in_progress,
                COUNT(*) FILTER (WHERE content_status = 'downloaded' 
                    AND download_completed_at >= CURRENT_DATE) as completed_today,
                COUNT(*) FILTER (WHERE content_status = 'failed' 
                    AND error_message LIKE '%download%'
                    AND updated_at >= CURRENT_DATE) as failed_today,
                MIN(meeting_date) FILTER (WHERE content_status IN ('discovered', 'download_pending')) as oldest_pending,
                MAX(meeting_date) FILTER (WHERE content_status IN ('discovered', 'download_pending')) as newest_pending
            FROM documents
            WHERE source_url IS NOT NULL
        """)
        
        # Extraction queue stats
        extraction_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE content_status IN ('downloaded', 'extraction_pending')) as pending,
                COUNT(*) FILTER (WHERE content_status = 'extracting') as in_progress,
                COUNT(*) FILTER (WHERE content_status = 'extracted' 
                    AND extraction_completed_at >= CURRENT_DATE) as completed_today,
                COUNT(*) FILTER (WHERE content_status = 'failed' 
                    AND error_message LIKE '%extract%'
                    AND updated_at >= CURRENT_DATE) as failed_today
            FROM documents
            WHERE local_path IS NOT NULL
        """)
        
        # AI queue stats (documents)
        ai_doc_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE content_status IN ('extracted', 'ai_pending')) as pending,
                COUNT(*) FILTER (WHERE content_status = 'ai_processing') as in_progress,
                COUNT(*) FILTER (WHERE content_status = 'complete' 
                    AND ai_completed_at >= CURRENT_DATE) as completed_today,
                COUNT(*) FILTER (WHERE content_status = 'failed' 
                    AND error_message LIKE '%ai%'
                    AND updated_at >= CURRENT_DATE) as failed_today
            FROM documents
            WHERE document_type != 'video' OR document_type IS NULL
        """)
        
        # AI queue stats (videos)
        ai_video_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE content_status = 'ai_pending' 
                    AND document_type = 'video') as pending,
                COUNT(*) FILTER (WHERE content_status = 'ai_processing' 
                    AND document_type = 'video') as in_progress,
                COUNT(*) FILTER (WHERE content_status = 'complete' 
                    AND document_type = 'video'
                    AND ai_completed_at >= CURRENT_DATE) as completed_today
            FROM documents
        """)
        
        # AI queue stats (events) - count ready vs blocked
        ai_event_stats = await conn.fetchrow("""
            SELECT 
                -- Total pending (no AI summary yet)
                COUNT(*) FILTER (WHERE e.ai_summary IS NULL OR e.ai_summary = '') as pending,
                -- Ready to process (all linked docs have summaries)
                COUNT(*) FILTER (
                    WHERE (e.ai_summary IS NULL OR e.ai_summary = '')
                    AND NOT EXISTS (
                        SELECT 1 FROM event_documents ed
                        JOIN documents d ON ed.document_id = d.id
                        WHERE ed.event_id = e.id
                          AND (d.ai_summary IS NULL OR d.ai_summary = '')
                          AND d.content_status != 'skipped'
                    )
                    AND EXISTS (
                        SELECT 1 FROM event_documents ed
                        JOIN documents d ON ed.document_id = d.id
                        WHERE ed.event_id = e.id
                          AND d.ai_summary IS NOT NULL
                    )
                ) as ready,
                -- Completed today
                COUNT(*) FILTER (WHERE e.ai_summary IS NOT NULL 
                    AND e.ai_summary_updated_at >= CURRENT_DATE) as completed_today
            FROM events e
        """)
        
        # AI queue stats (summaries) - count ready vs blocked
        ai_summary_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) FILTER (WHERE status IN ('pending', 'stale')) as pending,
                COUNT(*) FILTER (WHERE status = 'generating') as in_progress,
                COUNT(*) FILTER (WHERE status = 'completed' 
                    AND generation_completed_at >= CURRENT_DATE) as completed_today,
                COUNT(*) FILTER (WHERE status = 'failed' 
                    AND updated_at >= CURRENT_DATE) as failed_today
            FROM summaries
        """)
        
        # Currently active items
        active_downloads = await conn.fetch("""
            SELECT id, title, document_type, source_url, meeting_date
            FROM documents
            WHERE content_status = 'downloading'
            ORDER BY download_started_at DESC
            LIMIT 5
        """)
        
        active_extractions = await conn.fetch("""
            SELECT id, title, document_type, local_path, meeting_date
            FROM documents
            WHERE content_status = 'extracting'
            ORDER BY extraction_started_at DESC
            LIMIT 5
        """)
        
        active_ai = await conn.fetch("""
            SELECT id, title, document_type, meeting_date
            FROM documents
            WHERE content_status = 'ai_processing'
            ORDER BY ai_started_at DESC
            LIMIT 5
        """)
        
        # Recent failures
        recent_failures = await conn.fetch("""
            SELECT id, title, document_type, error_message, retry_count, updated_at
            FROM documents
            WHERE content_status = 'failed'
            ORDER BY updated_at DESC
            LIMIT 10
        """)
        
        # Calculate totals
        total_pending = (
            (download_stats['pending'] or 0) +
            (extraction_stats['pending'] or 0) +
            (ai_doc_stats['pending'] or 0) +
            (ai_video_stats['pending'] or 0) +
            (ai_event_stats['pending'] or 0) +
            (ai_summary_stats['pending'] or 0)
        )
        
        total_in_progress = (
            (download_stats['in_progress'] or 0) +
            (extraction_stats['in_progress'] or 0) +
            (ai_doc_stats['in_progress'] or 0) +
            (ai_summary_stats['in_progress'] or 0)
        )
        
        # Determine health
        is_healthy = True
        health_message = "All systems operational"
        
        if (download_stats['failed_today'] or 0) > 10:
            is_healthy = False
            health_message = "High download failure rate"
        elif (ai_doc_stats['failed_today'] or 0) > 10:
            is_healthy = False
            health_message = "High AI processing failure rate"
        
        return {
            "download": {
                "pending": download_stats['pending'] or 0,
                "in_progress": download_stats['in_progress'] or 0,
                "completed_today": download_stats['completed_today'] or 0,
                "failed_today": download_stats['failed_today'] or 0,
                "oldest_pending_date": download_stats['oldest_pending'].isoformat() if download_stats['oldest_pending'] else None,
                "newest_pending_date": download_stats['newest_pending'].isoformat() if download_stats['newest_pending'] else None,
            },
            "extraction": {
                "pending": extraction_stats['pending'] or 0,
                "in_progress": extraction_stats['in_progress'] or 0,
                "completed_today": extraction_stats['completed_today'] or 0,
                "failed_today": extraction_stats['failed_today'] or 0,
            },
            "ai_documents": {
                "pending": ai_doc_stats['pending'] or 0,
                "in_progress": ai_doc_stats['in_progress'] or 0,
                "completed_today": ai_doc_stats['completed_today'] or 0,
                "failed_today": ai_doc_stats['failed_today'] or 0,
            },
            "ai_videos": {
                "pending": ai_video_stats['pending'] or 0,
                "in_progress": ai_video_stats['in_progress'] or 0,
                "completed_today": ai_video_stats['completed_today'] or 0,
            },
            "ai_events": {
                "pending": ai_event_stats['pending'] or 0,
                "ready": ai_event_stats['ready'] or 0,
                "blocked": (ai_event_stats['pending'] or 0) - (ai_event_stats['ready'] or 0),
                "completed_today": ai_event_stats['completed_today'] or 0,
            },
            "ai_summaries": {
                "pending": ai_summary_stats['pending'] or 0,
                "in_progress": ai_summary_stats['in_progress'] or 0,
                "completed_today": ai_summary_stats['completed_today'] or 0,
                "failed_today": ai_summary_stats['failed_today'] or 0,
            },
            "active_downloads": [dict(r) for r in active_downloads],
            "active_extractions": [dict(r) for r in active_extractions],
            "active_ai": [dict(r) for r in active_ai],
            "recent_failures": [dict(r) for r in recent_failures],
            "total_pending": total_pending,
            "total_in_progress": total_in_progress,
            "is_healthy": is_healthy,
            "health_message": health_message,
            "last_updated": datetime.utcnow().isoformat(),
        }

    async def get_queue_items(
        self,
        conn,
        status: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get queue items with optional filtering.
        For paginated UI display.
        """
        conditions = ["1=1"]
        params = []
        param_idx = 1
        
        if status:
            conditions.append(f"content_status = ${param_idx}")
            params.append(status)
            param_idx += 1
        
        if content_type:
            if content_type == "video":
                conditions.append(f"document_type = 'video'")
            else:
                conditions.append(f"document_type != 'video' OR document_type IS NULL")
        
        where_clause = " AND ".join(conditions)
        
        params.extend([limit, offset])
        
        query = f"""
            SELECT 
                d.id, d.title, d.document_type, d.content_status,
                d.source_url, d.local_path, d.meeting_date,
                d.error_message, d.retry_count,
                d.discovered_at, d.download_started_at, d.download_completed_at,
                d.extraction_started_at, d.extraction_completed_at,
                d.ai_started_at, d.ai_completed_at,
                d.file_size_bytes,
                s.name as source_name
            FROM documents d
            JOIN sources s ON d.source_id = s.id
            WHERE {where_clause}
            ORDER BY 
                CASE d.content_status
                    WHEN 'downloading' THEN 1
                    WHEN 'extracting' THEN 2
                    WHEN 'ai_processing' THEN 3
                    WHEN 'discovered' THEN 4
                    WHEN 'download_pending' THEN 5
                    WHEN 'extraction_pending' THEN 6
                    WHEN 'ai_pending' THEN 7
                    WHEN 'failed' THEN 8
                    ELSE 9
                END,
                meeting_date DESC NULLS LAST,
                created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]

    # =========================================================================
    # Retry Management
    # =========================================================================
    
    async def retry_failed_items(
        self,
        conn,
        max_retries: int = 3,
        limit: int = 10,
    ) -> int:
        """
        Reset failed items that haven't exceeded max retries.
        Returns number of items reset.
        """
        # PostgreSQL doesn't support LIMIT in UPDATE, so use subquery
        result = await conn.execute("""
            UPDATE documents
            SET 
                content_status = CASE
                    WHEN local_path IS NOT NULL AND content_markdown IS NULL THEN 'extraction_pending'
                    WHEN local_path IS NOT NULL THEN 'ai_pending'
                    ELSE 'download_pending'
                END,
                error_message = NULL,
                updated_at = NOW()
            WHERE id IN (
                SELECT id FROM documents
                WHERE content_status = 'failed'
                  AND retry_count < $1
                  AND (retry_after IS NULL OR retry_after <= NOW())
                LIMIT $2
            )
        """, max_retries, limit)
        
        # Parse "UPDATE N" response
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            logger.info(f"Reset {count} failed items for retry")
        return count

    async def clear_stale_processing(
        self,
        conn,
        timeout_minutes: int = 30,
    ) -> int:
        """
        Reset items stuck in processing state for too long.
        Returns number of items reset.
        """
        result = await conn.execute("""
            UPDATE documents
            SET 
                content_status = CASE content_status
                    WHEN 'downloading' THEN 'download_pending'
                    WHEN 'extracting' THEN 'extraction_pending'
                    WHEN 'ai_processing' THEN 'ai_pending'
                    ELSE content_status
                END,
                error_message = 'Reset: processing timed out',
                updated_at = NOW()
            WHERE content_status IN ('downloading', 'extracting', 'ai_processing')
              AND updated_at < NOW() - INTERVAL '1 minute' * $1
        """, timeout_minutes)
        
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            logger.warning(f"Reset {count} stale processing items")
        return count

    async def backfill_video_meeting_dates(self, conn) -> int:
        """
        Parse meeting dates from video titles for videos missing meeting_date.
        
        Government video titles usually include the meeting date:
        - "City Council Meeting - January 28, 2025"
        - "Planning Commission - May 27, 2025"
        - "Board Meeting 11/20"
        
        Returns number of videos updated.
        """
        import re
        from datetime import datetime
        
        # Get videos without meeting_date
        videos = await conn.fetch("""
            SELECT id, title FROM documents
            WHERE document_type = 'video'
              AND meeting_date IS NULL
              AND title IS NOT NULL
        """)
        
        if not videos:
            return 0
        
        # Date patterns to try
        date_patterns = [
            # "January 28, 2025"
            (r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}', 
             ["%B %d, %Y", "%B %d %Y"]),
            # "Jan 28, 2025"
            (r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}',
             ["%b %d, %Y", "%b %d %Y"]),
            # "1/28/2025" or "01/28/2025"
            (r'\d{1,2}/\d{1,2}/\d{4}', ["%m/%d/%Y"]),
            # "2025-01-28"
            (r'\d{4}-\d{2}-\d{2}', ["%Y-%m-%d"]),
            # "11/20" (short month/day)
            (r'\b(\d{1,2})/(\d{1,2})\b(?!/)', None),  # Special handling
        ]
        
        updated_count = 0
        current_year = datetime.now().year
        
        for video in videos:
            title = video['title']
            meeting_date = None
            
            for pattern, formats in date_patterns:
                match = re.search(pattern, title)
                if not match:
                    continue
                    
                date_str = match.group(0)
                
                if formats is None:
                    # Handle short date (m/d)
                    try:
                        parsed = datetime.strptime(f"{date_str}/{current_year}", "%m/%d/%Y")
                        # If more than 6 months in future, assume last year
                        if (parsed - datetime.now()).days > 180:
                            parsed = datetime.strptime(f"{date_str}/{current_year - 1}", "%m/%d/%Y")
                        meeting_date = parsed
                        break
                    except ValueError:
                        continue
                else:
                    for fmt in formats:
                        try:
                            meeting_date = datetime.strptime(
                                date_str.replace(",", "").strip(), 
                                fmt.replace(",", "")
                            )
                            break
                        except ValueError:
                            continue
                    if meeting_date:
                        break
            
            if meeting_date:
                await conn.execute("""
                    UPDATE documents 
                    SET meeting_date = $1, updated_at = NOW()
                    WHERE id = $2
                """, meeting_date, video['id'])
                updated_count += 1
                logger.debug(f"Set meeting_date for video '{title}' to {meeting_date.date()}")
        
        if updated_count > 0:
            logger.info(f"Backfilled meeting_date for {updated_count} videos")
        
        return updated_count
