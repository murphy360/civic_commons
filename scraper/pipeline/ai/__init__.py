"""
AI processing modules for civic event data.

This package provides AI-powered processing capabilities:
- GeminiClient: HTTP client for Gemini API
- extract_pdf_text: PDF text extraction utility
- DocumentLinker: Intelligent document-to-event matching
- DocumentSummarizer: AI summaries for documents (generated once, reused)
- EventSummarizer: AI-generated event summaries
- SummaryGenerator: Cascading AI summaries (event → daily → weekly → etc.)
- SummaryCascadeManager: Manages cascade updates when documents change
- AIEventProcessor: Main facade for all AI operations (in parent module)
"""

from .client import GeminiClient, get_gemini_client
from .pdf_extractor import extract_pdf_text, extract_pdf_text_sync
from .linker import DocumentLinker
from .doc_summarizer import DocumentSummarizer
from .summarizer import EventSummarizer
from .summary import SummaryGenerator, SummaryType, get_period_bounds
from .cascade import SummaryCascadeManager

__all__ = [
    "GeminiClient",
    "get_gemini_client", 
    "extract_pdf_text",
    "extract_pdf_text_sync",
    "DocumentLinker",
    "DocumentSummarizer",
    "EventSummarizer",
    "SummaryGenerator",
    "SummaryType",
    "get_period_bounds",
    "SummaryCascadeManager",
]
