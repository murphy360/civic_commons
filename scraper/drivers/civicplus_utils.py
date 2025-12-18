"""
Shared utilities for CivicPlus drivers.

CivicPlus is a common CMS for municipal websites. These utilities
handle date parsing, document type inference, and other common tasks
shared across the various CivicPlus drivers.
"""

import re
from datetime import datetime
from typing import Optional

from models import EventType, DocumentType


# =============================================================================
# Date Parsing Patterns
# =============================================================================

# Matches: "Agenda for December 9, 2025 Regular Council Meeting"
DATE_PATTERN = re.compile(
    r"(?:Agenda for\s+)?(\w+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE
)

# Matches: "Regular", "Special", "Work Session", etc.
MEETING_TYPE_PATTERN = re.compile(
    r"(Regular|Special|Work Session|Executive Session|Public Hearing)",
    re.IGNORECASE
)

# Compressed date format: "Dec2, 2025" or "Nov17, 2025"
COMPRESSED_DATE_PATTERN = re.compile(
    r"([A-Z][a-z]{2})(\d{1,2}),?\s*(\d{4})"
)

# Date in URL: _MMDDYYYY-
URL_DATE_PATTERN = re.compile(r"_(\d{2})(\d{2})(\d{4})-")


# =============================================================================
# Date Extraction Functions
# =============================================================================

def extract_date_from_title(title: str) -> Optional[datetime]:
    """
    Extract date from an agenda title.
    
    Examples:
    - "Agenda for December 9, 2025 Regular Council Meeting"
    - "Agenda for October 28, 2025 Regular Council Meeting (PDF)"
    """
    match = DATE_PATTERN.search(title)
    if not match:
        return None
    
    date_str = match.group(1)
    
    formats = [
        "%B %d, %Y",      # December 9, 2025
        "%B %d %Y",       # December 9 2025
        "%b %d, %Y",      # Dec 9, 2025
        "%b %d %Y",       # Dec 9 2025
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


def extract_date_from_compressed(text: str) -> Optional[datetime]:
    """
    Extract date from compressed format like "Dec2, 2025" or "Nov17, 2025".
    """
    match = COMPRESSED_DATE_PATTERN.search(text)
    if match:
        month_abbr = match.group(1)
        day = match.group(2)
        year = match.group(3)
        try:
            return datetime.strptime(f"{month_abbr} {day}, {year}", "%b %d, %Y")
        except ValueError:
            pass
    return None


def extract_date_from_url(url: str) -> Optional[datetime]:
    """
    Extract date from a CivicPlus document URL.
    
    CivicPlus URLs embed dates in MMDDYYYY format:
    - /AgendaCenter/ViewFile/Agenda/_02272025-1386 -> Feb 27, 2025
    - /AgendaCenter/ViewFile/Minutes/_12092024-1371 -> Dec 9, 2024
    """
    match = URL_DATE_PATTERN.search(url)
    if match:
        month = match.group(1)
        day = match.group(2)
        year = match.group(3)
        try:
            return datetime.strptime(f"{month}/{day}/{year}", "%m/%d/%Y")
        except ValueError:
            pass
    return None


# =============================================================================
# Type Inference
# =============================================================================

def infer_event_type(title: str) -> EventType:
    """Infer event type from meeting title."""
    title_lower = title.lower()
    
    if "hearing" in title_lower:
        return EventType.HEARING
    elif "work session" in title_lower or "workshop" in title_lower:
        return EventType.WORKSHOP
    else:
        return EventType.MEETING


def infer_doc_type(link_text: str, href: str) -> DocumentType:
    """Infer document type from link text and URL."""
    text = link_text.lower()
    href_lower = href.lower()
    
    # Check for video URLs first
    if any(video_host in href_lower for video_host in [
        'youtube.com', 'youtu.be', 'vimeo.com', 'wistia.com',
        'video', 'media', 'stream'
    ]):
        return DocumentType.VIDEO
    
    # Check URL patterns (more reliable for CivicPlus)
    if "viewfile/minutes" in href_lower or "viewfile/archivedminutes" in href_lower:
        return DocumentType.MINUTES
    elif "viewfile/archivedagenda" in href_lower:
        return DocumentType.AGENDA
    elif "viewfile/agenda" in href_lower:
        return DocumentType.AGENDA
    
    # Fall back to text matching
    if "minute" in text:
        return DocumentType.MINUTES
    elif "agenda" in text:
        return DocumentType.AGENDA
    elif "packet" in text:
        return DocumentType.PACKET
    elif "video" in text or "media" in text or "recording" in text:
        return DocumentType.VIDEO
    elif "resolution" in text:
        return DocumentType.RESOLUTION
    elif "ordinance" in text:
        return DocumentType.ORDINANCE
    else:
        return DocumentType.OTHER


# =============================================================================
# URL Validation
# =============================================================================

def is_document_url(href: str) -> bool:
    """
    Check if a URL points to an actual document vs a navigation page.
    
    CivicPlus has various URL patterns:
    - /ViewFile/Agenda/_MMDDYYYY-XXX -> actual document (PDF)
    - /ViewFile/Minutes/_MMDDYYYY-XXX -> actual document (PDF)
    - /PreviousVersions/_MMDDYYYY-XXX -> navigation page (skip)
    """
    href_lower = href.lower()
    
    # Skip non-http links
    if not (href_lower.startswith('http://') or href_lower.startswith('https://')):
        return False
    
    # Skip PreviousVersions pages
    if "/previousversions/" in href_lower:
        return False
    
    # Accept ViewFile URLs
    if "/viewfile/" in href_lower:
        return True
    
    # Accept direct PDF links
    if href_lower.endswith('.pdf'):
        return True
    
    # Accept video URLs (only actual videos, not channel pages)
    if 'youtu.be/' in href_lower:
        return True
    if 'youtube.com/watch' in href_lower:
        return True
    if 'vimeo.com/' in href_lower and not href_lower.endswith('vimeo.com/'):
        return True
    
    return False


# =============================================================================
# Title Cleaning
# =============================================================================

def clean_meeting_title(raw_title: str, category_name: str) -> str:
    """
    Clean up a meeting title for display.
    
    Input: "Agenda for December 9, 2025 Regular Council Meeting (PDF)"
    Output: "Regular Council Meeting"
    """
    # Remove "Agenda for DATE" prefix
    title = DATE_PATTERN.sub("", raw_title)
    
    # Remove common suffixes
    title = re.sub(r"\s*\(PDF\).*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*Opens in new window.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*-\s*AMENDED.*$", "", title, flags=re.IGNORECASE)
    
    # Clean whitespace
    title = " ".join(title.split())
    
    # If title is empty or too short, use category name
    if len(title) < 5:
        title = f"{category_name} Meeting"
    
    return title.strip()


# =============================================================================
# CivicPlus Module Constants
# =============================================================================

# CivicPlus module IDs are consistent across all CivicPlus sites
CIVICPLUS_MODULES = {
    "agenda": 65,
    "calendar": 58,
    "alerts": 63,
    "news": 1,
    "blog": 51,
    "jobs": 66,
}

# Note: Category CIDs (like "City-Council-2") are site-specific and should
# be configured in the city's YAML config file under civicplus.agenda_categories
# and civicplus.calendar_categories.
