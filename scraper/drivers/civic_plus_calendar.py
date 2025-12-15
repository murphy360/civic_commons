"""
Purpose: Driver for CivicPlus Calendar pages (community events, parks & rec, etc.)
Dependencies: httpx for HTTP, BeautifulSoup for HTML parsing
Consumed by: Worker for parks & recreation, community events
Side effects: HTTP requests to CivicPlus calendar

CivicPlus Calendar Structure (as seen on mytwinsburg.com):
- Main calendar at /Calendar.aspx
- Supports multiple calendar categories via CID parameter
- Calendar categories: Main Calendar (CID=14), Parks & Recreation (CID=22), etc.
- Event details at /Calendar.aspx?EID={event_id}
- Events show: title, date/time, location, description
- Can filter by date range with StartDate/EndDate parameters
- RSS feed available at /rss.aspx#calendar
- ICalendar feed at /iCalendar.aspx
"""

import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlencode

import httpx
from bs4 import BeautifulSoup, Tag

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


class CivicPlusCalendarDriver(BaseDriver):
    """
    Driver for CivicPlus Calendar pages.
    
    CivicPlus calendars display community events with categories like
    Parks & Recreation, Main Calendar, etc.
    
    Expected params in YAML config:
        base_url: Base URL of the city website
        calendar_ids: List of calendar category IDs to scrape
        days_ahead: Number of days into future to scrape (default: 90)
        days_back: Number of days into past to scrape (default: 30)
        
    Example config:
        - name: "Community Events"
          driver: "civic_plus_calendar"
          params:
            base_url: "https://www.mytwinsburg.com"
            calendar_ids:
              - 14  # Main Calendar
              - 22  # Parks & Recreation
            days_ahead: 90
    """
    
    # Regex patterns for parsing event dates
    DATE_PATTERN = re.compile(
        r"(\w+\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE
    )
    
    TIME_PATTERN = re.compile(
        r"(\d{1,2}:\d{2}\s*(?:AM|PM)?)\s*(?:-|to|–)\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?)",
        re.IGNORECASE
    )

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch events and documents from CivicPlus calendar."""
        events: list[Event] = []
        documents: list[Document] = []

        base_url = self.params.get("base_url", "").rstrip("/")
        calendar_ids = self.params.get("calendar_ids", [14])  # Default to main calendar
        days_ahead = self.params.get("days_ahead", 90)
        days_back = self.params.get("days_back", 7)  # Default: only 1 week back on initial
        
        # Support explicit date range (for backfill)
        start_date = self.params.get("start_date")
        end_date = self.params.get("end_date")
        backfill_mode = self.params.get("backfill_mode", False)
        
        if not base_url:
            raise ValueError("Missing required param: base_url")

        # Build calendar URL with category IDs
        cid_param = ",".join(str(cid) for cid in calendar_ids)
        
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": "CivicCommons/1.0 (civic data aggregator)"}
        ) as client:
            # Determine which months to fetch
            if backfill_mode and start_date and end_date:
                # Backfill: fetch specific month range
                months_to_fetch = self._get_months_in_range(start_date, end_date)
                self.log_info(
                    f"Backfill mode: fetching {len(months_to_fetch)} months "
                    f"({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})"
                )
            else:
                # Normal mode: calculate months based on days_ahead
                today = datetime.now()
                end_future = today + timedelta(days=days_ahead)
                start_past = today - timedelta(days=days_back)
                months_to_fetch = self._get_months_in_range(start_past, end_future)
                self.log_info(f"Normal mode: fetching {len(months_to_fetch)} months ({days_back} days back, {days_ahead} days ahead)")
            
            for year, month in months_to_fetch:
                # Build URL with month/year params
                calendar_url = f"{base_url}/Calendar.aspx?CID={cid_param}&month={month}&year={year}"
                self.log_info(f"Fetching calendar: {calendar_url}")
                
                # Fetch the calendar page
                await self.rate_limit_delay()
                response = await client.get(calendar_url)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")
                
                # Find all event entries on the calendar
                event_links = self._find_event_links(soup, base_url)
                
                self.log_info(f"Found {len(event_links)} event links for {year}-{month:02d}")
                
                # Fetch details for each event (now returns event and documents)
                for event_url in event_links:
                    await self.rate_limit_delay()
                    event, event_docs = await self._fetch_event_details(client, base_url, event_url)
                    if event:
                        # Filter by date range if in backfill mode
                        if backfill_mode and start_date and end_date:
                            if event.start_time:
                                event_date = event.start_time.date() if hasattr(event.start_time, 'date') else event.start_time
                                if isinstance(start_date, datetime):
                                    start_date = start_date.date()
                                if isinstance(end_date, datetime):
                                    end_date = end_date.date()
                                if not (start_date <= event_date <= end_date):
                                    continue  # Skip events outside date range
                        events.append(event)
                        documents.extend(event_docs)

        # Deduplicate events
        events = self._deduplicate_events(events)
        
        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents
    
    def _get_months_in_range(self, start_date, end_date) -> list[tuple[int, int]]:
        """Get list of (year, month) tuples for a date range."""
        from datetime import date
        
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()
        
        months = []
        current = start_date.replace(day=1)
        end_month = end_date.replace(day=1)
        
        while current <= end_month:
            months.append((current.year, current.month))
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        return months
    
    def _find_event_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """
        Find all event detail links on the calendar page.
        
        Returns list of absolute URLs.
        """
        event_urls = set()
        
        # Look for links to event detail pages (Calendar.aspx?EID=xxx)
        for link in soup.select('a[href*="Calendar.aspx?EID="], a[href*="calendar.aspx?EID="]'):
            href = link.get("href", "")
            if href:
                full_url = urljoin(base_url, href)
                event_urls.add(full_url)
        
        # Also look for event blocks that might have different link patterns
        for event_block in soup.select(".calendarEvent, .event-item, .calendar-event"):
            link = event_block.select_one("a[href]")
            if link:
                href = link.get("href", "")
                if "EID=" in href or "event" in href.lower():
                    full_url = urljoin(base_url, href)
                    event_urls.add(full_url)
        
        return list(event_urls)
    
    async def _fetch_event_details(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        event_url: str,
    ) -> Optional[Event]:
        """
        Fetch and parse a single event's detail page.
        
        Returns Event or None if parsing fails.
        """
        try:
            response = await client.get(event_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find event title - look for specific CivicPlus element first
            title = None
            title_elem = soup.select_one('[id$="eventTitle"]')
            if title_elem:
                title = title_elem.get_text(strip=True)
            else:
                for selector in ["h1", "h2.detailTitle", ".event-title", ".calendarTitle"]:
                    elem = soup.select_one(selector)
                    if elem:
                        text = elem.get_text(strip=True)
                        if len(text) > 3 and text.lower() not in ["calendar", "event", "event details"]:
                            title = text
                            break
            
            if not title:
                self.log_debug(f"Could not find title for {event_url}")
                return None, []
            
            # Skip cancelled events but log them
            if "cancelled" in title.lower() or "canceled" in title.lower():
                self.log_debug(f"Skipping cancelled event: {title}")
                return None, []
            
            # Find event date/time - prefer the hidden ISO date field
            starts_at = None
            ends_at = None
            
            # CivicPlus uses itemprop="startDate" with ISO format in a hidden div
            start_date_elem = soup.select_one('[itemprop="startDate"]')
            if start_date_elem:
                iso_date = start_date_elem.get_text(strip=True)
                try:
                    starts_at = datetime.fromisoformat(iso_date)
                except ValueError:
                    pass
            
            # Try to extract end time from the time display
            if starts_at:
                time_elem = soup.select_one('[id$="_time"] .specificDetailItem')
                if time_elem:
                    time_text = time_elem.get_text(strip=True)
                    # Parse "10:00 AM - 12:30 PM" format
                    time_match = self.TIME_PATTERN.search(time_text)
                    if time_match:
                        end_time_str = time_match.group(2).strip()
                        end_time = self._parse_time(end_time_str)
                        if end_time:
                            ends_at = starts_at.replace(
                                hour=end_time.hour,
                                minute=end_time.minute
                            )
            
            # Fallback date parsing
            if not starts_at:
                for selector in [".eventDate", ".event-date", ".calendarDate", '[id$="_dateDiv"]']:
                    elem = soup.select_one(selector)
                    if elem:
                        date_text = elem.get_text(strip=True)
                        starts_at, ends_at = self._parse_datetime(date_text)
                        if starts_at:
                            break
            
            if not starts_at:
                self.log_debug(f"Could not find date for {event_url}")
                return None, []
            
            # Find location using structured schema.org data
            location = self._extract_location(soup)
            
            # Find description using itemprop="description"
            description = self._extract_description(soup)
            
            # Extract linked documents (PDFs, etc.)
            documents = self._extract_documents(soup, base_url, title)
            
            # Determine event type based on title/content
            event_type = self._infer_event_type(title, description or "")
            
            event = Event(
                title=title,
                starts_at=starts_at,
                ends_at=ends_at,
                event_type=event_type,
                location=location,
                description=description,
                source_url=event_url,
            )
            
            return event, documents
            
        except Exception as e:
            self.log_error(f"Error fetching event {event_url}: {e}")
            return None, []
    
    def _extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract structured location from CivicPlus schema.org markup.
        
        Returns formatted address string.
        """
        location_parts = []
        
        # Try to get facility/location name
        name_elem = soup.select_one('[itemprop="location"] [itemprop="name"]')
        if name_elem:
            name = name_elem.get_text(strip=True)
            if name:
                location_parts.append(name)
        
        # Get street address
        street_elem = soup.select_one('[itemprop="streetAddress"]')
        if street_elem:
            location_parts.append(street_elem.get_text(strip=True))
        
        # Get city, state, zip
        city = soup.select_one('[itemprop="addressLocality"]')
        state = soup.select_one('[itemprop="addressRegion"]')
        postal = soup.select_one('[itemprop="postalCode"]')
        
        city_state_zip = []
        if city:
            city_state_zip.append(city.get_text(strip=True))
        if state:
            city_state_zip.append(state.get_text(strip=True))
        if postal:
            city_state_zip.append(postal.get_text(strip=True))
        
        if city_state_zip:
            location_parts.append(" ".join(city_state_zip))
        
        if location_parts:
            return ", ".join(location_parts)
        
        # Fallback to generic location selectors
        for selector in [".eventLocation", ".event-location", ".location", "address"]:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(strip=True)
        
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract event description, preserving key formatting.
        
        Returns cleaned description text.
        """
        # CivicPlus uses itemprop="description" for the main content
        desc_elem = soup.select_one('[itemprop="description"]')
        
        if not desc_elem:
            # Fallback selectors
            for selector in [".eventDescription", ".event-description", ".description", ".content", ".fr-view"]:
                desc_elem = soup.select_one(selector)
                if desc_elem:
                    break
        
        if not desc_elem:
            return None
        
        # Get text with some structure preserved
        # Replace <br> and </p> with newlines for readability
        for br in desc_elem.find_all("br"):
            br.replace_with("\n")
        for p in desc_elem.find_all("p"):
            p.insert_after("\n\n")
        
        description = desc_elem.get_text(separator=" ", strip=True)
        
        # Clean up excessive whitespace while preserving paragraphs
        description = re.sub(r'\n\s*\n', '\n\n', description)
        description = re.sub(r' +', ' ', description)
        
        # Limit length but try to break at sentence
        if len(description) > 2000:
            description = description[:2000]
            # Try to break at last sentence
            last_period = description.rfind('.')
            if last_period > 1500:
                description = description[:last_period + 1]
        
        return description.strip() if description else None
    
    def _extract_documents(
        self, 
        soup: BeautifulSoup, 
        base_url: str,
        event_title: str,
    ) -> list[Document]:
        """
        Extract linked documents (PDFs, etc.) from the event page.
        
        Returns list of Document objects.
        """
        documents = []
        
        # CivicPlus uses itemprop="documents" for document lists
        doc_list = soup.select_one('[itemprop="documents"]')
        
        if doc_list:
            for link in doc_list.select('a[href]'):
                href = link.get('href', '')
                if not href:
                    continue
                
                full_url = urljoin(base_url, href)
                doc_title = link.get_text(strip=True)
                
                # Determine document type from CSS class or URL
                doc_type = DocumentType.OTHER
                link_classes = link.get('class', [])
                if isinstance(link_classes, str):
                    link_classes = [link_classes]
                
                if 'pdf' in link_classes or '.pdf' in href.lower() or 'DocumentCenter' in href:
                    doc_type = DocumentType.ATTACHMENT
                
                if doc_title:
                    documents.append(Document(
                        title=doc_title,
                        doc_type=doc_type,
                        original_url=full_url,
                    ))
        
        # Also look for other document links in the page
        for link in soup.select('a[href*="DocumentCenter"], a[href$=".pdf"]'):
            href = link.get('href', '')
            if not href:
                continue
            
            full_url = urljoin(base_url, href)
            
            # Skip if already found
            if any(d.original_url == full_url for d in documents):
                continue
            
            doc_title = link.get_text(strip=True) or "Attached Document"
            
            documents.append(Document(
                title=doc_title,
                doc_type=DocumentType.ATTACHMENT,
                original_url=full_url,
            ))
        
        return documents
        """
        Parse date and time from text.
        
        Returns tuple of (starts_at, ends_at).
        """
        starts_at = None
        ends_at = None
        
        # Find date
        date_match = self.DATE_PATTERN.search(text)
        if not date_match:
            return None, None
        
        date_str = date_match.group(1)
        
        # Try various date formats
        date_formats = [
            "%B %d, %Y",      # December 9, 2025
            "%B %d %Y",       # December 9 2025
            "%b %d, %Y",      # Dec 9, 2025
            "%b %d %Y",       # Dec 9 2025
            "%m/%d/%Y",       # 12/9/2025
        ]
        
        parsed_date = None
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        
        if not parsed_date:
            return None, None
        
        # Find time range
        time_match = self.TIME_PATTERN.search(text)
        if time_match:
            start_time_str = time_match.group(1).strip()
            end_time_str = time_match.group(2).strip()
            
            start_time = self._parse_time(start_time_str)
            end_time = self._parse_time(end_time_str)
            
            if start_time:
                starts_at = parsed_date.replace(
                    hour=start_time.hour,
                    minute=start_time.minute
                )
            if end_time:
                ends_at = parsed_date.replace(
                    hour=end_time.hour,
                    minute=end_time.minute
                )
        else:
            # Look for single time
            single_time = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM)?)", text, re.IGNORECASE)
            if single_time:
                start_time = self._parse_time(single_time.group(1))
                if start_time:
                    starts_at = parsed_date.replace(
                        hour=start_time.hour,
                        minute=start_time.minute
                    )
        
        # If no time found, default to midnight
        if not starts_at:
            starts_at = parsed_date
        
        return starts_at, ends_at
    
    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """Parse a time string like '9:00 AM' or '6:30 PM'."""
        time_str = time_str.strip().upper()
        
        formats = [
            "%I:%M %p",   # 9:00 AM
            "%I:%M%p",    # 9:00AM
            "%H:%M",      # 14:00
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        
        return None
    
    def _infer_event_type(self, title: str, description: str) -> EventType:
        """Infer event type from title and description."""
        text = (title + " " + description).lower()
        
        if any(kw in text for kw in ["meeting", "commission", "board", "council"]):
            return EventType.MEETING
        elif any(kw in text for kw in ["hearing", "public hearing"]):
            return EventType.HEARING
        elif any(kw in text for kw in ["workshop", "training", "class", "seminar"]):
            return EventType.WORKSHOP
        elif any(kw in text for kw in ["program", "camp", "club"]):
            return EventType.PROGRAM
        elif any(kw in text for kw in ["deadline", "due", "registration"]):
            return EventType.DEADLINE
        else:
            return EventType.COMMUNITY
    
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
