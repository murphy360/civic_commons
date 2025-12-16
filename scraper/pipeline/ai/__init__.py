"""
AI processing modules for civic event data.

This package provides AI-powered processing capabilities:
- GeminiClient: HTTP client for Gemini API
- extract_pdf_text: PDF text extraction utility
- DocumentLinker: Intelligent document-to-event matching
- DocumentSummarizer: AI summaries for documents (generated once, reused)
- EventSummarizer: AI-generated event summaries
- AIEventProcessor: Main facade for all AI operations (in parent module)
"""

from .client import GeminiClient, get_gemini_client
from .pdf_extractor import extract_pdf_text, extract_pdf_text_sync
from .linker import DocumentLinker
from .doc_summarizer import DocumentSummarizer
from .summarizer import EventSummarizer

__all__ = [
    "GeminiClient",
    "get_gemini_client", 
    "extract_pdf_text",
    "extract_pdf_text_sync",
    "DocumentLinker",
    "DocumentSummarizer",
    "EventSummarizer",
]
