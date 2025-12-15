"""
Purpose: Document data model for PDFs, agendas, minutes, and other files
Dependencies: Pydantic for validation
Consumed by: drivers/, pipeline/pdf.py, pipeline/storage.py
Side effects: None
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Categories of civic documents."""
    AGENDA = "agenda"           # Meeting agendas
    MINUTES = "minutes"         # Meeting minutes
    PACKET = "packet"           # Full board packets
    RESOLUTION = "resolution"   # Adopted resolutions
    ORDINANCE = "ordinance"     # Adopted ordinances
    REPORT = "report"           # Staff reports
    PRESENTATION = "presentation"  # Slide decks
    NOTICE = "notice"           # Public notices
    ATTACHMENT = "attachment"   # General event attachments
    OTHER = "other"


class Document(BaseModel):
    """
    Represents a document scraped from a source.
    
    Documents may be associated with events (e.g., meeting minutes)
    or standalone (e.g., public notices).
    """
    
    # Identity
    id: UUID = Field(default_factory=uuid4)
    external_id: Optional[str] = None  # ID from source system
    
    # Core fields
    title: str
    doc_type: DocumentType = DocumentType.OTHER
    
    # Source
    original_url: str  # URL where document was found
    
    # Local storage (set after download)
    file_path: Optional[str] = None  # Local file path
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    
    # Extracted content (set after processing)
    content_markdown: Optional[str] = None  # Full extracted text as markdown
    content_hash: Optional[str] = None  # SHA-256 for deduplication
    
    # AI-generated (set after summarization)
    summary: Optional[str] = None
    key_points: list[str] = Field(default_factory=list)
    
    # Metadata
    published_at: Optional[datetime] = None  # When source says it was published
    meeting_date: Optional[datetime] = None  # For minutes/agendas
    tags: list[str] = Field(default_factory=list)
    
    # Timestamps (set by storage layer)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        use_enum_values = True
