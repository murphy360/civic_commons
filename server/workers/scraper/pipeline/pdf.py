"""
Purpose: PDF download and text extraction pipeline
Dependencies: httpx for download, pymupdf4llm for extraction
Consumed by: main.py after drivers return documents
Side effects: Downloads files, reads/writes to filesystem
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

import httpx
import pymupdf4llm

from models import Document

logger = logging.getLogger("civic.pdf")


class PdfProcessor:
    """
    Handles PDF download and text extraction.
    
    Pipeline:
    1. Download PDF from original_url
    2. Save to local storage
    3. Extract text to markdown using pymupdf4llm
    4. Calculate content hash for deduplication
    """

    def __init__(self, storage_dir: Path):
        """
        Initialize the PDF processor.
        
        Args:
            storage_dir: Directory to store downloaded PDFs
        """
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def process(
        self,
        document: Document,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Document:
        """
        Process a document: download, save, extract text.
        
        Args:
            document: Document with original_url set
            client: Optional HTTP client (creates one if not provided)
            
        Returns:
            Updated Document with file_path, content_markdown, content_hash
        """
        should_close_client = client is None
        if client is None:
            client = httpx.AsyncClient()

        try:
            # Download the PDF
            file_path = await self._download(document, client)
            document.file_path = str(file_path)

            # Extract text
            markdown = self._extract_text(file_path)
            document.content_markdown = markdown

            # Calculate hash
            document.content_hash = self._calculate_hash(file_path)

            logger.info(f"Processed: {document.title}")
            return document

        except Exception as e:
            logger.error(f"Failed to process {document.original_url}: {e}")
            raise
        finally:
            if should_close_client:
                await client.aclose()

    async def _download(
        self,
        document: Document,
        client: httpx.AsyncClient,
    ) -> Path:
        """
        Download PDF from URL to local storage.
        
        Returns:
            Path to downloaded file
        """
        # Generate filename from URL or title
        url_hash = hashlib.md5(document.original_url.encode()).hexdigest()[:8]
        safe_title = "".join(c for c in document.title if c.isalnum() or c in " -_")[:50]
        filename = f"{safe_title}_{url_hash}.pdf"
        
        file_path = self.storage_dir / filename

        # Skip if already downloaded
        if file_path.exists():
            logger.debug(f"Already downloaded: {filename}")
            return file_path

        # Download
        logger.info(f"Downloading: {document.original_url}")
        response = await client.get(
            document.original_url,
            follow_redirects=True,
            timeout=60.0,
        )
        response.raise_for_status()

        # Verify it's a PDF
        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type.lower() and not response.content[:4] == b"%PDF":
            raise ValueError(f"Not a PDF: {content_type}")

        # Save
        file_path.write_bytes(response.content)
        document.file_size_bytes = len(response.content)
        document.mime_type = "application/pdf"

        logger.info(f"Saved: {filename} ({len(response.content)} bytes)")
        return file_path

    def _extract_text(self, file_path: Path) -> str:
        """
        Extract text from PDF as markdown.
        
        Uses pymupdf4llm which preserves:
        - Document structure (headings, lists)
        - Tables (as markdown tables)
        - Page breaks
        """
        try:
            # pymupdf4llm returns markdown-formatted text
            markdown = pymupdf4llm.to_markdown(str(file_path))
            return markdown
        except Exception as e:
            logger.error(f"Text extraction failed for {file_path}: {e}")
            # Return empty string rather than failing entirely
            return ""

    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of file for deduplication."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def cleanup_old_files(self, max_age_days: int = 30) -> int:
        """
        Remove old downloaded files.
        
        Args:
            max_age_days: Delete files older than this
            
        Returns:
            Number of files deleted
        """
        import time
        
        deleted = 0
        cutoff = time.time() - (max_age_days * 24 * 60 * 60)
        
        for file_path in self.storage_dir.glob("*.pdf"):
            if file_path.stat().st_mtime < cutoff:
                file_path.unlink()
                deleted += 1
                logger.debug(f"Deleted old file: {file_path.name}")
        
        if deleted:
            logger.info(f"Cleaned up {deleted} old files")
        
        return deleted

