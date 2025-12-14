"""
Purpose: Driver for CivicPlus-powered municipal websites (agenda centers)
Dependencies: httpx for HTTP, BeautifulSoup for HTML parsing
Consumed by: Worker for city council, planning commission, etc.
Side effects: HTTP requests to CivicPlus agenda center
"""

from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


class CivicPlusDriver(BaseDriver):
    """
    Driver for CivicPlus Agenda Center pages.
    
    CivicPlus is a common CMS for municipal websites. Their agenda centers
    typically have a predictable HTML structure.
    
    Expected params in YAML config:
        base_url: Base URL of the city website
        agenda_center_id: ID of the agenda center (found in URL)
        
    Example config:
        - name: "City Council"
          driver: "civic_plus"
          params:
            base_url: "https://www.mytwinsburg.com"
            agenda_center_id: "5"
    """

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch meetings and documents from CivicPlus agenda center."""
        events: list[Event] = []
        documents: list[Document] = []

        base_url = self.params.get("base_url")
        agenda_center_id = self.params.get("agenda_center_id")

        if not base_url:
            raise ValueError("Missing required param: base_url")
        if not agenda_center_id:
            raise ValueError("Missing required param: agenda_center_id")

        # Construct agenda center URL
        agenda_url = f"{base_url}/AgendaCenter"
        
        self.log_info(f"Fetching agenda center: {agenda_url}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Fetch the main agenda page
            await self.rate_limit_delay()
            response = await client.get(agenda_url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            # Parse meetings from the agenda center
            # CivicPlus typically uses table rows or list items
            meeting_items = soup.select(".MeetingRow, .meeting-row, tr.meeting")
            
            for item in meeting_items:
                event, docs = await self._parse_meeting_item(
                    client=client,
                    base_url=base_url,
                    item=item,
                )
                if event:
                    events.append(event)
                    documents.extend(docs)

            # Also try the upcoming meetings widget
            upcoming = soup.select(".upcoming-meeting, .UpcomingMeeting")
            for item in upcoming:
                event, docs = await self._parse_upcoming_item(
                    client=client,
                    base_url=base_url,
                    item=item,
                )
                if event:
                    events.append(event)
                    documents.extend(docs)

        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents

    async def _parse_meeting_item(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        item,
    ) -> tuple[Optional[Event], list[Document]]:
        """
        Parse a single meeting row from the agenda table.
        
        Returns:
            Tuple of (Event or None, list of Documents)
        """
        documents: list[Document] = []
        
        try:
            # Extract meeting title
            title_elem = item.select_one(".MeetingTitle, .meeting-title, td:first-child")
            if not title_elem:
                return None, documents
            title = title_elem.get_text(strip=True)

            # Extract date
            date_elem = item.select_one(".MeetingDate, .meeting-date, td:nth-child(2)")
            if not date_elem:
                return None, documents
            date_text = date_elem.get_text(strip=True)
            starts_at = self._parse_date(date_text)

            if not starts_at:
                self.log_debug(f"Could not parse date: {date_text}")
                return None, documents

            # Create event
            event = Event(
                title=title,
                starts_at=starts_at,
                event_type=EventType.MEETING,
                source_url=base_url,
            )

            # Find document links (agenda, minutes, packet)
            for link in item.select("a[href*='.pdf'], a[href*='ViewFile']"):
                href = link.get("href", "")
                if not href:
                    continue

                doc_url = urljoin(base_url, href)
                doc_type = self._infer_doc_type(link.get_text())

                doc = Document(
                    title=f"{title} - {doc_type.value.title()}",
                    doc_type=doc_type,
                    original_url=doc_url,
                    meeting_date=starts_at,
                )
                documents.append(doc)

            return event, documents

        except Exception as e:
            self.log_error(f"Error parsing meeting item: {e}")
            return None, documents

    async def _parse_upcoming_item(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        item,
    ) -> tuple[Optional[Event], list[Document]]:
        """Parse an upcoming meeting widget item."""
        # Similar structure to _parse_meeting_item
        # Implemented separately in case format differs
        return await self._parse_meeting_item(client, base_url, item)

    def _parse_date(self, date_text: str) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.
        
        Handles common CivicPlus date formats.
        """
        # Common formats in CivicPlus
        formats = [
            "%B %d, %Y",           # January 15, 2025
            "%m/%d/%Y",            # 01/15/2025
            "%m-%d-%Y",            # 01-15-2025
            "%Y-%m-%d",            # 2025-01-15
            "%b %d, %Y",           # Jan 15, 2025
            "%m/%d/%Y %I:%M %p",   # 01/15/2025 7:00 PM
        ]

        date_text = date_text.strip()
        
        for fmt in formats:
            try:
                return datetime.strptime(date_text, fmt)
            except ValueError:
                continue

        return None

    def _infer_doc_type(self, link_text: str) -> DocumentType:
        """Infer document type from link text."""
        text = link_text.lower()
        
        if "agenda" in text:
            return DocumentType.AGENDA
        elif "minute" in text:
            return DocumentType.MINUTES
        elif "packet" in text:
            return DocumentType.PACKET
        elif "resolution" in text:
            return DocumentType.RESOLUTION
        elif "ordinance" in text:
            return DocumentType.ORDINANCE
        else:
            return DocumentType.OTHER
