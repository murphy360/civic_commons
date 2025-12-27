"""
Purpose: Unified queue processor - handles downloads, extraction, and AI in stages
Dependencies: queue_manager, downloader, pdf extraction, AI processors
Consumed by: main.py scheduler
Side effects: Downloads files, extracts text, generates AI summaries

This processor runs as scheduled jobs and processes the unified queue
in priority order (most recent dates first).
"""

import logging
import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.activity_logger_http import ActivityLoggerHTTP as ActivityLogger

logger = logging.getLogger("civic.queue_processor")


class QueueProcessor:
    """
    Processes the unified content queue through all stages:
    1. Downloads - Fetch files from source URLs
    2. Extraction - Convert PDFs to text/markdown
    3. AI Analysis - Generate summaries for documents, videos, events
    
    All stages prioritize by date (most recent/upcoming first).
    """

    def __init__(
        self,
        db_pool,
        queue_manager,
        document_downloader,
        settings=None,
        activity_logger: Optional["ActivityLogger"] = None,
    ):
        self.db_pool = db_pool
        self.queue_manager = queue_manager
        self.downloader = document_downloader
        self.settings = settings or {}
        self.activity = activity_logger
        
        # Processing limits
        self.download_batch_size = int(os.getenv("DOWNLOAD_BATCH_SIZE", "5"))
        self.extraction_batch_size = int(os.getenv("EXTRACTION_BATCH_SIZE", "3"))

    # =========================================================================
    # Download Stage
    # =========================================================================

    async def process_downloads(self) -> int:
        """
        Process the download queue.
        Returns number of items processed.
        """
        if not self.downloader:
            logger.debug("No downloader configured, skipping download processing")
            return 0
        
        processed = 0
        
        try:
            async with self.db_pool.acquire() as conn:
                # Get items pending download
                items = await self.queue_manager.get_download_queue(
                    conn, limit=self.download_batch_size
                )
                
                if not items:
                    logger.debug("Download queue: No items pending")
                    return 0
                
                logger.info(f"Download queue: Processing {len(items)} items")
                
                for item in items:
                    try:
                        await self._process_single_download(conn, item)
                        processed += 1
                    except Exception as e:
                        logger.warning(f"Download failed for '{item['title']}': {e}")
                        await self.queue_manager.mark_failed(
                            conn, item['id'], f"Download failed: {str(e)[:200]}"
                        )
                
                logger.info(f"Download queue: Completed {processed}/{len(items)} items")
                
        except Exception as e:
            logger.error(f"Download queue error: {e}")
        
        return processed

    async def _process_single_download(self, conn, item: dict) -> None:
        """Download a single document."""
        doc_id = item['id']
        
        # Mark as downloading
        await self.queue_manager.mark_downloading(conn, doc_id)
        
        # Log download started
        if self.activity:
            await self.activity.log_download_started(
                doc_id, item['title'], 
                source_name=item.get('source_name'),
                city_id=item.get('city_id'),
                url=item.get('source_url'),
            )
        
        try:
            result = await self.downloader.download(
                url=item['source_url'],
                source_name=item['source_name'],
                document_id=doc_id,
                title=item['title'],
            )
            
            if result and result.get('local_path'):
                await self.queue_manager.mark_downloaded(
                    conn, doc_id,
                    local_path=result['local_path'],
                    file_size_bytes=result.get('file_size', 0),
                    mime_type=result.get('mime_type', 'application/octet-stream'),
                    file_hash=result.get('file_hash', ''),
                )
                logger.debug(f"Downloaded: {item['title']}")
                
                # Log download completed
                if self.activity:
                    await self.activity.log_download_completed(
                        doc_id, item['title'],
                        file_size=result.get('file_size'),
                        source_name=item.get('source_name'),
                        city_id=item.get('city_id'),
                    )
            else:
                # Non-downloadable URL (HTML page, etc.)
                await self.queue_manager.mark_skipped(
                    conn, doc_id, "Not a downloadable file"
                )
                logger.debug(f"Skipped non-downloadable: {item['title']}")
                
        except Exception as e:
            await self.queue_manager.mark_failed(
                conn, doc_id, f"Download error: {str(e)[:200]}"
            )
            
            # Log download failed
            if self.activity:
                await self.activity.log_download_failed(
                    doc_id, item['title'], str(e),
                    source_name=item.get('source_name'),
                    city_id=item.get('city_id'),
                )
            raise

    # =========================================================================
    # Extraction Stage
    # =========================================================================

    async def process_extractions(self) -> int:
        """
        Process the extraction queue (PDF → text).
        Returns number of items processed.
        """
        processed = 0
        
        try:
            async with self.db_pool.acquire() as conn:
                items = await self.queue_manager.get_extraction_queue(
                    conn, limit=self.extraction_batch_size
                )
                
                if not items:
                    logger.debug("Extraction queue: No items pending")
                    return 0
                
                logger.info(f"Extraction queue: Processing {len(items)} items")
                
                for item in items:
                    try:
                        await self._process_single_extraction(conn, item)
                        processed += 1
                    except Exception as e:
                        logger.warning(f"Extraction failed for '{item['title']}': {e}")
                        await self.queue_manager.mark_failed(
                            conn, item['id'], f"Extraction failed: {str(e)[:200]}"
                        )
                
                logger.info(f"Extraction queue: Completed {processed}/{len(items)} items")
                
        except Exception as e:
            logger.error(f"Extraction queue error: {e}")
        
        return processed

    async def _process_single_extraction(self, conn, item: dict) -> None:
        """Extract text from a single document."""
        doc_id = item['id']
        local_path = item['local_path']
        mime_type = item.get('mime_type', '')
        
        # Mark as extracting
        await self.queue_manager.mark_extracting(conn, doc_id)
        
        # Log extraction started
        if self.activity:
            await self.activity.log_extraction_started(
                doc_id, item['title'],
                source_name=item.get('source_name'),
            )
        
        try:
            content_text = None
            content_markdown = None
            
            # Only extract from PDFs
            if mime_type == 'application/pdf' or (local_path and local_path.endswith('.pdf')):
                content_text, content_markdown = await self._extract_pdf_content(local_path)
            elif mime_type.startswith('text/'):
                # Plain text files
                full_path = self._get_full_path(local_path)
                if full_path.exists():
                    content_text = full_path.read_text(encoding='utf-8', errors='ignore')
                    content_markdown = content_text
            else:
                # Non-extractable file type
                await self.queue_manager.mark_skipped(
                    conn, doc_id, f"Cannot extract text from {mime_type}"
                )
                return
            
            if content_markdown or content_text:
                await self.queue_manager.mark_extracted(
                    conn, doc_id, content_text, content_markdown
                )
                logger.debug(f"Extracted: {item['title']}")
                
                # Log extraction completed
                if self.activity:
                    char_count = len(content_markdown or content_text or '')
                    await self.activity.log_extraction_completed(
                        doc_id, item['title'],
                        char_count=char_count,
                        source_name=item.get('source_name'),
                    )
            else:
                await self.queue_manager.mark_skipped(
                    conn, doc_id, "No text content extracted"
                )
                logger.debug(f"No content extracted: {item['title']}")
                
        except Exception as e:
            await self.queue_manager.mark_failed(
                conn, doc_id, f"Extraction error: {str(e)[:200]}"
            )
            
            # Log extraction failed
            if self.activity:
                await self.activity.log_extraction_failed(
                    doc_id, item['title'], str(e),
                    source_name=item.get('source_name'),
                )
            raise

    async def _extract_pdf_content(self, local_path: str) -> tuple[Optional[str], Optional[str]]:
        """Extract text and markdown from a PDF file."""
        try:
            import pymupdf4llm
            
            full_path = self._get_full_path(local_path)
            if not full_path.exists():
                logger.warning(f"PDF file not found: {full_path}")
                return None, None
            
            # Extract as markdown (preserves tables, formatting)
            content_markdown = pymupdf4llm.to_markdown(str(full_path))
            
            # Also get plain text
            import fitz
            doc = fitz.open(str(full_path))
            content_text = ""
            for page in doc:
                content_text += page.get_text()
            doc.close()
            
            return content_text.strip(), content_markdown.strip()
            
        except Exception as e:
            logger.warning(f"PDF extraction error for {local_path}: {e}")
            return None, None

    def _get_full_path(self, local_path: str) -> Path:
        """Get full filesystem path for a stored document."""
        storage_dir = os.getenv("DOCUMENT_STORAGE_DIR", "/data/documents")
        return Path(storage_dir) / local_path

    # Note: AI processing has been moved to the MCP service

    # =========================================================================
    # Maintenance
    # =========================================================================

    async def run_maintenance(self) -> dict:
        """
        Run maintenance tasks:
        - Reset stuck items
        - Retry failed items
        - Backfill video meeting dates from titles
        Returns stats about what was done.
        """
        stats = {
            "stuck_reset": 0,
            "failed_retried": 0,
            "video_dates_backfilled": 0,
        }
        
        try:
            async with self.db_pool.acquire() as conn:
                # Reset items stuck in processing state
                stats["stuck_reset"] = await self.queue_manager.clear_stale_processing(
                    conn, timeout_minutes=30
                )
                
                # Retry failed items that haven't exceeded max retries
                stats["failed_retried"] = await self.queue_manager.retry_failed_items(
                    conn, max_retries=3, limit=20
                )
                
                # Backfill missing video meeting dates from titles
                stats["video_dates_backfilled"] = await self.queue_manager.backfill_video_meeting_dates(conn)
                
        except Exception as e:
            logger.error(f"Maintenance error: {e}")
        
        return stats

    # =========================================================================
    # Status
    # =========================================================================

    async def get_status(self) -> dict:
        """Get comprehensive queue status for UI."""
        try:
            async with self.db_pool.acquire() as conn:
                return await self.queue_manager.get_queue_status(conn)
        except Exception as e:
            logger.error(f"Status fetch error: {e}")
            return {
                "error": str(e),
                "is_healthy": False,
                "health_message": "Failed to fetch queue status",
            }

    async def is_busy(self) -> bool:
        """Check if queue has significant pending work."""
        try:
            async with self.db_pool.acquire() as conn:
                status = await self.queue_manager.get_queue_status(conn)
                return status.get('total_pending', 0) > 10
        except Exception:
            return False

