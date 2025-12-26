"""
PDF text extraction utility.

This module provides functions to extract text content from PDF files
for AI analysis and processing.
"""

import logging
from typing import Optional

logger = logging.getLogger("civic.ai.pdf")


async def extract_pdf_text(
    local_path: str, 
    max_pages: int = 3,
    base_dir: str = "/data/documents",
) -> Optional[str]:
    """
    Extract text from a PDF file for AI analysis.
    
    Args:
        local_path: Path to the PDF file (can be relative or absolute)
        max_pages: Maximum number of pages to extract (to limit token usage)
        base_dir: Base directory for relative paths
        
    Returns:
        Extracted text or None if extraction fails
    """
    try:
        import fitz  # PyMuPDF
        
        # Handle relative paths
        if not local_path.startswith('/'):
            full_path = f"{base_dir}/{local_path}"
        else:
            full_path = local_path
        
        doc = fitz.open(full_path)
        text_parts = []
        
        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]
            text_parts.append(page.get_text())
        
        doc.close()
        
        full_text = "\n".join(text_parts)
        logger.debug(f"Extracted {len(full_text)} chars from PDF: {local_path}")
        return full_text
        
    except ImportError:
        logger.debug("PyMuPDF not available for PDF text extraction")
        return None
    except FileNotFoundError:
        logger.warning(f"PDF file not found: {local_path}")
        return None
    except Exception as e:
        logger.warning(f"Failed to extract PDF text from {local_path}: {e}")
        return None


def extract_pdf_text_sync(
    local_path: str,
    max_pages: int = 3,
    base_dir: str = "/data/documents",
) -> Optional[str]:
    """
    Synchronous version of extract_pdf_text.
    
    Useful for contexts where async is not available.
    
    Args:
        local_path: Path to the PDF file (can be relative or absolute)
        max_pages: Maximum number of pages to extract
        base_dir: Base directory for relative paths
        
    Returns:
        Extracted text or None if extraction fails
    """
    try:
        import fitz  # PyMuPDF
        
        # Handle relative paths
        if not local_path.startswith('/'):
            full_path = f"{base_dir}/{local_path}"
        else:
            full_path = local_path
        
        doc = fitz.open(full_path)
        text_parts = []
        
        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]
            text_parts.append(page.get_text())
        
        doc.close()
        
        full_text = "\n".join(text_parts)
        logger.debug(f"Extracted {len(full_text)} chars from PDF: {local_path}")
        return full_text
        
    except ImportError:
        logger.debug("PyMuPDF not available for PDF text extraction")
        return None
    except FileNotFoundError:
        logger.warning(f"PDF file not found: {local_path}")
        return None
    except Exception as e:
        logger.warning(f"Failed to extract PDF text from {local_path}: {e}")
        return None

