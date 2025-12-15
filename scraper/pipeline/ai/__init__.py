"""
AI processing modules for civic event data.

This package provides AI-powered processing capabilities:
- GeminiClient: HTTP client for Gemini API
- extract_pdf_text: PDF text extraction utility
- AIEventProcessor: Main facade for all AI operations (in parent module)
"""

from .client import GeminiClient, get_gemini_client
from .pdf_extractor import extract_pdf_text, extract_pdf_text_sync

__all__ = [
    "GeminiClient",
    "get_gemini_client", 
    "extract_pdf_text",
    "extract_pdf_text_sync",
]
