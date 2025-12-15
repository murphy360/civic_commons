"""
Purpose: Driver for CivicPlus-powered municipal websites (agenda centers)
Dependencies: httpx for HTTP, BeautifulSoup for HTML parsing
Consumed by: Worker for city council, planning commission, etc.
Side effects: HTTP requests to CivicPlus agenda center

CivicPlus AgendaCenter Structure (as seen on mytwinsburg.com):
- Main page shows collapsible category sections (City Council, Planning Commission, etc.)
- Each category has a table with meeting rows
- Each row has: Agenda link | Minutes link (optional) | Media link (optional) | Download
- Date is embedded in the agenda title: "Agenda for December 9, 2025 Regular Council Meeting"
- PDF URLs use pattern: /AgendaCenter/ViewFile/Agenda/_MMDDYYYY-XXXX
- RSS feed available at /rss.aspx#agendaCenter
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


class CivicPlusDriver(BaseDriver):
    """
    Driver for CivicPlus Agenda Center pages.
    
    CivicPlus is a common CMS for municipal websites. Their agenda centers
    have categories (boards/commissions) with tables of meeting agendas.
    
    Expected params in YAML config:
        base_url: Base URL of the city website
        categories: Optional list of category names to scrape (all if not specified)
        max_years: Number of years of history to scrape (default: 2)
        
    Example config:
        - name: "City Council"
          driver: "civic_plus"
          params:
            base_url: "https://www.mytwinsburg.com"
            categories:
              - "City Council"
              - "Planning Commission"
            max_years: 2
    """
    
    # Regex to extract date from agenda title
    # Matches: "Agenda for December 9, 2025 Regular Council Meeting"
    DATE_PATTERN = re.compile(
        r"(?:Agenda for\s+)?(\w+\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE
    )
    
    # Regex to extract meeting type from title
    MEETING_TYPE_PATTERN = re.compile(
        r"(Regular|Special|Work Session|Executive Session|Public Hearing)",
        re.IGNORECASE
    )

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch meetings and documents from CivicPlus agenda center."""
        events: list[Event] = []
        documents: list[Document] = []

        base_url = self.params.get("base_url", "").rstrip("/")
        categories_filter = self.params.get("categories", [])
        
        if not base_url:
            raise ValueError("Missing required param: base_url")

        # Construct agenda center URL
        agenda_url = f"{base_url}/AgendaCenter"
        
        self.log_info(f"Fetching agenda center: {agenda_url}")

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": "CivicCommons/1.0 (civic data aggregator)"}
        ) as client:
            # Fetch the main agenda page
            await self.rate_limit_delay()
            response = await client.get(agenda_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find all category sections
            # CivicPlus uses divs with class "catAgendaRow" or similar
            # Each category section has a header and a table of agendas
            categories = self._find_categories(soup, categories_filter)
            
            self.log_info(f"Found {len(categories)} categories to process")

            for category_name, category_elem in categories:
                self.log_debug(f"Processing category: {category_name}")
                
                # Parse the agenda table for this category
                cat_events, cat_docs = self._parse_category_table(
                    base_url=base_url,
                    category_name=category_name,
                    category_elem=category_elem,
                )
                events.extend(cat_events)
                documents.extend(cat_docs)

        # Deduplicate events by source_url and starts_at
        events = self._deduplicate_events(events)
        
        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents
    
    def _find_categories(
        self, soup: BeautifulSoup, filter_names: list[str]
    ) -> list[tuple[str, Tag]]:
        """
        Find all category sections in the agenda center.
        
        Returns list of (category_name, element) tuples.
        """
        categories = []
        
        # CivicPlus uses various structures. Try multiple patterns:
        
        # Pattern 1: Collapsible sections with class containing "agenda" or "category"
        # The mytwinsburg.com page uses spans/divs that toggle visibility
        
        # Look for table/section containers that follow category headers
        # Each category header is typically an anchor or div with category name
        
        # Find all agenda row tables
        tables = soup.select("table")
        
        for table in tables:
            # Look for the category name in a preceding header element
            prev = table.find_previous(["h2", "h3", "h4", "span", "div", "a"])
            if prev:
                # Get text, clean it up
                cat_name = prev.get_text(strip=True)
                # Skip if it's a generic header or too short
                if len(cat_name) < 3 or cat_name.lower() in ["search", "download", "tools"]:
                    continue
                
                # Filter by category names if specified
                if filter_names:
                    if not any(f.lower() in cat_name.lower() for f in filter_names):
                        continue
                
                categories.append((cat_name, table))
        
        # Pattern 2: Look for sections by content pattern
        # Each section has rows with "Agenda for DATE" text
        if not categories:
            # Find all rows containing agenda links
            agenda_rows = soup.select("tr")
            current_category = "General"
            current_rows = []
            
            for row in agenda_rows:
                # Check if this row has an agenda link
                agenda_link = row.select_one('a[href*="AgendaCenter"], a[href*="ViewFile"]')
                if agenda_link:
                    # Group with current category
                    if current_category not in [c[0] for c in categories]:
                        categories.append((current_category, row.parent))
        
        return categories

    def _parse_category_table(
        self,
        base_url: str,
        category_name: str,
        category_elem: Tag,
    ) -> tuple[list[Event], list[Document]]:
        """
        Parse all meeting rows from a category's table.
        
        Returns tuple of (events, documents).
        """
        events: list[Event] = []
        documents: list[Document] = []
        
        # Find all rows in this table/section
        rows = category_elem.select("tr") if category_elem.name == "table" else [category_elem]
        
        for row in rows:
            event, docs = self._parse_agenda_row(base_url, category_name, row)
            if event:
                events.append(event)
                documents.extend(docs)
        
        return events, documents
    
    def _parse_agenda_row(
        self,
        base_url: str,
        category_name: str,
        row: Tag,
    ) -> tuple[Optional[Event], list[Document]]:
        """
        Parse a single agenda row.
        
        CivicPlus rows typically have:
        - Column 1: Agenda link with full title including date
        - Column 2: Minutes link (if available)
        - Column 3: Media/Video link (if available)
        - Column 4: Download dropdown
        
        Returns tuple of (Event or None, list of Documents).
        """
        documents: list[Document] = []
        
        try:
            # Find all links in this row
            links = row.select("a")
            if not links:
                return None, documents
            
            # Find the agenda link (usually the first substantive link)
            agenda_link = None
            agenda_text = None
            
            for link in links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                
                # Skip download dropdowns, navigation links
                if not href or "Download" in text or href.startswith("javascript"):
                    continue
                
                # Look for agenda link (contains "Agenda" or links to ViewFile)
                if "agenda" in text.lower() or "ViewFile/Agenda" in href:
                    agenda_link = link
                    agenda_text = text
                    break
                
                # Fall back to first real link
                if not agenda_link and len(text) > 10:
                    agenda_link = link
                    agenda_text = text
            
            if not agenda_text:
                return None, documents
            
            # Extract date from agenda title
            starts_at = self._extract_date_from_title(agenda_text)
            if not starts_at:
                self.log_debug(f"Could not parse date from: {agenda_text}")
                return None, documents
            
            # Clean up meeting title
            meeting_title = self._clean_meeting_title(agenda_text, category_name)
            
            # Determine event type
            event_type = self._infer_event_type(agenda_text)
            
            # Build source URL
            source_url = base_url + "/AgendaCenter"
            
            # Create the event
            event = Event(
                title=meeting_title,
                starts_at=starts_at,
                event_type=event_type,
                source_url=source_url,
                location="Council Chambers",  # Default for most meetings
            )
            
            # Parse document links from this row
            for link in links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                
                # Skip non-document links
                if not href or href.startswith("javascript"):
                    continue
                if "Download" in text:
                    continue
                
                # Build full URL
                doc_url = urljoin(base_url, href)
                
                # Determine document type
                doc_type = self._infer_doc_type(text, href)
                
                # Create document
                doc = Document(
                    title=f"{meeting_title} - {doc_type.value.replace('_', ' ').title()}",
                    doc_type=doc_type,
                    original_url=doc_url,
                    meeting_date=starts_at,
                )
                documents.append(doc)
            
            return event, documents
            
        except Exception as e:
            self.log_error(f"Error parsing agenda row: {e}")
            return None, documents
    
    def _extract_date_from_title(self, title: str) -> Optional[datetime]:
        """
        Extract date from an agenda title.
        
        Examples:
        - "Agenda for December 9, 2025 Regular Council Meeting"
        - "Agenda for October 28, 2025 Regular Council Meeting (PDF)"
        """
        match = self.DATE_PATTERN.search(title)
        if not match:
            return None
        
        date_str = match.group(1)
        
        # Try various formats
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
    
    def _clean_meeting_title(self, raw_title: str, category_name: str) -> str:
        """
        Clean up a meeting title for display.
        
        Input: "Agenda for December 9, 2025 Regular Council Meeting (PDF)"
        Output: "City Council Regular Meeting" or "Regular Council Meeting"
        """
        # Remove "Agenda for DATE" prefix
        title = self.DATE_PATTERN.sub("", raw_title)
        
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
    
    def _infer_event_type(self, title: str) -> EventType:
        """Infer event type from meeting title."""
        title_lower = title.lower()
        
        if "hearing" in title_lower:
            return EventType.HEARING
        elif "work session" in title_lower or "workshop" in title_lower:
            return EventType.WORKSHOP
        else:
            return EventType.MEETING
    
    def _infer_doc_type(self, link_text: str, href: str) -> DocumentType:
        """Infer document type from link text and URL."""
        text = link_text.lower()
        href_lower = href.lower()
        
        if "minute" in text:
            return DocumentType.MINUTES
        elif "agenda" in text or "viewfile/agenda" in href_lower:
            return DocumentType.AGENDA
        elif "packet" in text:
            return DocumentType.PACKET
        elif "video" in text or "media" in text:
            return DocumentType.OTHER  # Video links handled separately
        elif "resolution" in text:
            return DocumentType.RESOLUTION
        elif "ordinance" in text:
            return DocumentType.ORDINANCE
        else:
            return DocumentType.OTHER
    
    def _deduplicate_events(self, events: list[Event]) -> list[Event]:
        """Remove duplicate events based on title and date."""
        seen = set()
        unique = []
        
        for event in events:
            key = (event.title, event.starts_at.date() if event.starts_at else None)
            if key not in seen:
                seen.add(key)
                unique.append(event)
        
        return unique
