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
from typing import Optional

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
        doc_summarizer=None,
        ai_processor=None,
        settings=None,
    ):
        self.db_pool = db_pool
        self.queue_manager = queue_manager
        self.downloader = document_downloader
        self.doc_summarizer = doc_summarizer
        self.ai_processor = ai_processor
        self.settings = settings or {}
        
        # Processing limits
        self.download_batch_size = int(os.getenv("DOWNLOAD_BATCH_SIZE", "5"))
        self.extraction_batch_size = int(os.getenv("EXTRACTION_BATCH_SIZE", "3"))
        self.ai_batch_size = int(os.getenv("AI_QUEUE_BATCH_SIZE", "1"))
        self.ai_max_age_days = int(os.getenv("AI_SUMMARY_MAX_AGE_DAYS", "365"))

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
            else:
                await self.queue_manager.mark_skipped(
                    conn, doc_id, "No text content extracted"
                )
                logger.debug(f"No content extracted: {item['title']}")
                
        except Exception as e:
            await self.queue_manager.mark_failed(
                conn, doc_id, f"Extraction error: {str(e)[:200]}"
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

    # =========================================================================
    # AI Analysis Stage
    # =========================================================================

    async def process_ai_queue(self) -> int:
        """
        Process the unified AI queue (documents, videos, events, summaries).
        Returns number of items processed.
        """
        if not self.doc_summarizer or not self.doc_summarizer.enabled:
            logger.debug("AI processing disabled, skipping")
            return 0
        
        processed = 0
        
        try:
            async with self.db_pool.acquire() as conn:
                items = await self.queue_manager.get_ai_queue(
                    conn, 
                    limit=self.ai_batch_size,
                    max_age_days=self.ai_max_age_days,
                )
                
                if not items:
                    logger.debug("AI queue: No items pending")
                    return 0
                
                logger.info(f"AI queue: Processing {len(items)} items")
                
                for item in items:
                    try:
                        item_type = item['item_type']
                        
                        if item_type == 'document':
                            await self._process_document_ai(conn, item)
                        elif item_type == 'video':
                            await self._process_video_ai(conn, item)
                        elif item_type == 'event':
                            await self._process_event_ai(conn, item)
                        elif item_type == 'summary':
                            await self._process_summary_ai(conn, item)
                        
                        processed += 1
                        
                    except Exception as e:
                        logger.warning(f"AI processing failed for '{item['title']}': {e}")
                
                logger.info(f"AI queue: Completed {processed}/{len(items)} items")
                
        except Exception as e:
            logger.error(f"AI queue error: {e}")
        
        return processed

    async def _process_document_ai(self, conn, item: dict) -> None:
        """Generate AI summary for a document."""
        doc_id = item['id']
        
        await self.queue_manager.mark_ai_processing(conn, doc_id)
        
        try:
            result = await self.doc_summarizer.generate_summary(
                title=item['title'],
                document_type=item['document_type'],
                content_text=item['content_markdown'],
                local_path=item['local_path'],
            )
            
            if result:
                await self.queue_manager.mark_complete(
                    conn, doc_id,
                    ai_summary=result.text_with_footer,
                    model_used=result.model_name,
                )
                logger.debug(f"AI summary generated: {item['title']}")
            else:
                await self.queue_manager.mark_failed(
                    conn, doc_id, "AI summary generation returned no result"
                )
                
        except Exception as e:
            await self.queue_manager.mark_failed(
                conn, doc_id, f"AI error: {str(e)[:200]}"
            )
            raise

    async def _process_video_ai(self, conn, item: dict) -> None:
        """Generate AI summary for a video (transcript extraction)."""
        doc_id = item['id']
        video_url = item['source_url']
        
        await self.queue_manager.mark_ai_processing(conn, doc_id)
        
        try:
            result = await self.doc_summarizer.generate_summary(
                title=item['title'],
                document_type='video',
                video_url=video_url,
            )
            
            if result:
                await self.queue_manager.mark_complete(
                    conn, doc_id,
                    ai_summary=result.text_with_footer,
                    model_used=result.model_name,
                )
                logger.debug(f"Video summary generated: {item['title']}")
            else:
                await self.queue_manager.mark_failed(
                    conn, doc_id, "Video summary generation returned no result"
                )
                
        except Exception as e:
            await self.queue_manager.mark_failed(
                conn, doc_id, f"Video AI error: {str(e)[:200]}"
            )
            raise

    async def _process_event_ai(self, conn, item: dict) -> None:
        """Generate AI summary for an event."""
        if not self.ai_processor:
            return
        
        event_id = item['id']
        
        try:
            # Get event details with linked documents
            event_row = await conn.fetchrow("""
                SELECT id, title, description, start_time, location, category
                FROM events WHERE id = $1
            """, event_id)
            
            if not event_row:
                return
            
            event = {
                'id': event_row['id'],
                'title': event_row['title'],
                'description': event_row['description'],
                'start_time': event_row['start_time'].isoformat() if event_row['start_time'] else None,
                'location': event_row['location'],
                'category': event_row['category'],
            }
            
            # Get linked documents with summaries
            doc_rows = await conn.fetch("""
                SELECT d.id, d.title, d.document_type, ed.relationship, d.ai_summary
                FROM event_documents ed
                JOIN documents d ON ed.document_id = d.id
                WHERE ed.event_id = $1 AND d.ai_summary IS NOT NULL
            """, event_id)
            
            documents = [dict(r) for r in doc_rows]
            
            # Generate event summary
            summary = await self.ai_processor.generate_event_summary(
                event=event, sources=[], documents=documents
            )
            
            if summary:
                await conn.execute("""
                    UPDATE events SET ai_summary = $1, ai_summary_updated_at = NOW()
                    WHERE id = $2
                """, summary, event_id)
                logger.debug(f"Event summary generated: {item['title']}")
                
        except Exception as e:
            logger.warning(f"Event AI processing failed: {e}")

    async def _process_summary_ai(self, conn, item: dict) -> None:
        """Generate period summary (weekly, monthly, etc.)."""
        # This would use the existing cascade system
        # For now, just log
        logger.debug(f"Summary generation queued: {item['title']}")

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
