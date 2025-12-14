"""
Purpose: Event data model for meetings, hearings, and community events
Dependencies: Pydantic for validation, datetime for timestamps
Consumed by: drivers/, pipeline/storage.py
Side effects: None
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Categories of civic events."""
    MEETING = "meeting"           # Regular board/council meetings
    HEARING = "hearing"           # Public hearings
    WORKSHOP = "workshop"         # Work sessions, study sessions
    COMMUNITY = "community"       # Community events, festivals
    PROGRAM = "program"           # Library programs, rec classes
    DEADLINE = "deadline"         # Application deadlines, voting deadlines


class Event(BaseModel):
    """
    Represents a civic event scraped from a source.
    
    This is the internal representation used by scrapers.
    It will be transformed for database storage.
    """
    
    # Identity
    id: UUID = Field(default_factory=uuid4)
    external_id: Optional[str] = None  # ID from source system
    
    # Core fields
    title: str
    description: Optional[str] = None
    event_type: EventType = EventType.MEETING
    
    # Timing
    starts_at: datetime
    ends_at: Optional[datetime] = None
    all_day: bool = False
    
    # Location
    location: Optional[str] = None
    address: Optional[str] = None
    virtual_url: Optional[str] = None  # Zoom/Teams link
    is_virtual: bool = False
    is_hybrid: bool = False
    
    # Source reference
    source_url: Optional[str] = None  # Link back to original
    
    # Metadata
    tags: list[str] = Field(default_factory=list)
    
    # Timestamps (set by storage layer)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        use_enum_values = True
