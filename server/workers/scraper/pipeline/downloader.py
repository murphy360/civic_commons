"""
Purpose: Download and store document attachments locally
Dependencies: httpx for downloads, aiofiles for async file I/O
Consumed by: main.py during document storage
Side effects: Downloads files to local storage
"""

import hashlib
import logging
import mimetypes
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote

import httpx

logger = logging.getLogger("civic.downloader")

# File extensions we'll download
ALLOWED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.csv', '.rtf', '.odt', '.ods', '.odp',
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
    '.mp3', '.mp4', '.wav', '.webm',
    '.zip', '.tar', '.gz',
}

# MIME types we'll download
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-powerpoint',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain',
    'text/csv',
    'application/rtf',
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'audio/mpeg',
    'video/mp4',
    'video/webm',
    'application/zip',
}


class DocumentDownloader:
    """
    Downloads document attachments and stores them locally.
    
    Features:
    - Async HTTP downloads with retry
    - Content-type validation
    - Deduplication by URL hash
    - Organized storage by source
    """

    def __init__(
        self,
        storage_dir: Path,
        max_file_size: int = 100 * 1024 * 1024,  # 100MB default
    ):
        """
        Initialize the downloader.
        
        Args:
            storage_dir: Base directory for storing downloads
            max_file_size: Maximum file size to download (bytes)
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = max_file_size
        
        # HTTP client settings
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def download(
        self,
        url: str,
        source_name: str,
        document_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Download a document from URL.
        
        Args:
            url: URL to download from
            source_name: Name of the source (for organizing storage)
            document_id: Optional database ID for the document
            title: Optional title for filename generation
            
        Returns:
            Dict with file info: {local_path, filename, mime_type, file_size, file_hash}
            None if download skipped or failed
        """
        if not url:
            return None
            
        # Check if URL looks downloadable
        if not self._is_downloadable_url(url):
            logger.debug(f"Skipping non-downloadable URL: {url}")
            return None

        # Generate storage path
        source_dir = self._get_source_dir(source_name)
        filename = self._generate_filename(url, title)
        local_path = source_dir / filename
        
        # Check if already downloaded
        if local_path.exists():
            logger.debug(f"Already downloaded: {filename}")
            return self._get_file_info(local_path)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=60.0,
                headers=self.headers,
            ) as client:
                # First do a HEAD request to check content type and size
                # Some servers (like CivicPlus) return 404 on HEAD but work with GET
                head_ok = False
                try:
                    head_response = await client.head(url)
                    if head_response.status_code == 200:
                        head_ok = True
                        content_type = head_response.headers.get("content-type", "").split(";")[0].strip()
                        content_length = int(head_response.headers.get("content-length", 0))
                        
                        # Check if we should download
                        if content_length > self.max_file_size:
                            logger.warning(f"File too large ({content_length} bytes): {url}")
                            return None
                            
                        if content_type and not self._is_allowed_content_type(content_type):
                            logger.debug(f"Skipping content type {content_type}: {url}")
                            return None
                    else:
                        logger.debug(f"HEAD returned {head_response.status_code}, trying GET: {url}")
                except httpx.HTTPError as e:
                    # HEAD failed with connection error, try GET anyway
                    logger.debug(f"HEAD request failed ({e}), trying GET: {url}")

                # Download the file
                logger.info(f"Downloading: {url}")
                response = await client.get(url)
                response.raise_for_status()
                
                content = response.content
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                
                # Validate content
                if len(content) > self.max_file_size:
                    logger.warning(f"Downloaded file too large ({len(content)} bytes): {url}")
                    return None
                    
                if len(content) < 100:
                    logger.warning(f"Downloaded file too small ({len(content)} bytes): {url}")
                    return None

                # Determine actual file extension from content type
                actual_ext = self._get_extension_from_content_type(content_type, content)
                if actual_ext and not filename.endswith(actual_ext):
                    # Update filename with correct extension
                    base_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
                    filename = f"{base_name}{actual_ext}"
                    local_path = source_dir / filename

                # Save the file
                local_path.write_bytes(content)
                
                logger.info(f"Saved: {filename} ({len(content)} bytes)")
                return self._get_file_info(local_path)

        except httpx.HTTPError as e:
            logger.error(f"HTTP error downloading {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None

    def _get_source_dir(self, source_name: str) -> Path:
        """Get or create directory for a source."""
        # Sanitize source name for filesystem
        safe_name = re.sub(r'[^\w\s-]', '', source_name).strip()
        safe_name = re.sub(r'[-\s]+', '-', safe_name).lower()
        
        source_dir = self.storage_dir / safe_name
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir

    def _generate_filename(self, url: str, title: Optional[str] = None) -> str:
        """Generate a unique filename from URL and optional title."""
        # Parse URL
        parsed = urlparse(url)
        path = unquote(parsed.path)
        
        # Try to get extension from URL
        ext = ''
        if '.' in path.split('/')[-1]:
            ext = '.' + path.split('.')[-1].lower()
            if len(ext) > 5:  # Invalid extension
                ext = ''
        
        # Generate base name
        if title:
            # Use title (sanitized)
            base = re.sub(r'[^\w\s-]', '', title).strip()
            base = re.sub(r'[-\s]+', '-', base)[:60]
        else:
            # Use last part of URL path
            base = path.split('/')[-1].rsplit('.', 1)[0]
            base = re.sub(r'[^\w\s-]', '', base).strip()[:60]
        
        if not base:
            base = "document"
        
        # Add URL hash for uniqueness
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        
        return f"{base}_{url_hash}{ext}"

    def _is_downloadable_url(self, url: str) -> bool:
        """Check if URL looks like a downloadable document."""
        if not url:
            return False
            
        # Skip obvious non-document URLs (be specific to avoid false positives)
        skip_patterns = [
            '/Calendar.aspx',
            'javascript:',
            'mailto:',
            '#',
        ]
        
        # Only skip AgendaCenter if it's the main page (no ViewFile)
        if '/AgendaCenter' in url and '/ViewFile' not in url and '/Previous' not in url:
            return False
            
        for pattern in skip_patterns:
            if pattern in url:
                return False
        
        # Check for document extensions
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        for ext in ALLOWED_EXTENSIONS:
            if path.endswith(ext):
                return True
        
        # Check for document-related URL patterns
        doc_patterns = [
            '/DocumentCenter/',
            '/document/',
            '/file/',
            '/download/',
            '/attachment/',
            '/ViewFile',
            '.pdf',
        ]
        for pattern in doc_patterns:
            if pattern.lower() in url.lower():
                return True
        
        return False

    def _is_allowed_content_type(self, content_type: str) -> bool:
        """Check if content type is allowed for download."""
        if not content_type:
            return True  # Allow if unknown
        
        content_type = content_type.lower()
        
        # Check exact matches
        if content_type in ALLOWED_MIME_TYPES:
            return True
        
        # Check partial matches
        if content_type.startswith('application/') or content_type.startswith('image/'):
            return True
            
        return False

    def _get_extension_from_content_type(
        self,
        content_type: str,
        content: bytes,
    ) -> Optional[str]:
        """Determine file extension from content type or magic bytes."""
        if not content_type:
            # Check magic bytes
            if content[:4] == b'%PDF':
                return '.pdf'
            if content[:4] == b'PK\x03\x04':  # ZIP (docx, xlsx, etc.)
                return '.zip'  # Would need more analysis for specific type
            return None
        
        # Map content type to extension
        ext = mimetypes.guess_extension(content_type)
        if ext:
            return ext
            
        # Manual mappings for common types
        type_map = {
            'application/pdf': '.pdf',
            'application/msword': '.doc',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.ms-excel': '.xls',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'text/plain': '.txt',
            'text/csv': '.csv',
        }
        return type_map.get(content_type.lower())

    def _get_file_info(self, local_path: Path) -> dict:
        """Get info about a downloaded file."""
        content = local_path.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        
        # Guess MIME type
        mime_type, _ = mimetypes.guess_type(str(local_path))
        if not mime_type and content[:4] == b'%PDF':
            mime_type = 'application/pdf'
        
        # Return path relative to storage directory for URL generation
        try:
            relative_path = local_path.relative_to(self.storage_dir)
        except ValueError:
            # Fallback to just filename if not under storage_dir
            relative_path = local_path.name
        
        return {
            'local_path': str(relative_path),
            'filename': local_path.name,
            'mime_type': mime_type or 'application/octet-stream',
            'file_size': len(content),
            'file_hash': file_hash,
        }

    def get_relative_path(self, local_path: str) -> str:
        """Get path relative to storage directory for URL generation."""
        try:
            return str(Path(local_path).relative_to(self.storage_dir))
        except ValueError:
            return local_path

