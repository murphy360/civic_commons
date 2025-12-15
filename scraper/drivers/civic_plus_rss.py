"""
Purpose: Driver for CivicPlus RSS feeds - simpler alternative to HTML scraping
Dependencies: httpx for HTTP, feedparser for RSS parsing
Consumed by: Worker for agenda center, calendar, alerts, news
Side effects: HTTP requests to CivicPlus RSS feeds

CivicPlus RSS Feed Structure:
- Base URL: /RSSFeed.aspx
- Modules (ModID):
  - 65: Agenda Center
  - 58: Calendar
  - 63: Alert Center (emergencies, traffic, weather)
  - 1: News Flash
  - 51: Blog
  - 66: Jobs
- Categories (CID):
  - "All-0" for all items in a module
  - "Category-Name-ID" for specific category (e.g., "City-Council-2")
  
Example feeds:
- All Agendas: /RSSFeed.aspx?ModID=65&CID=All-0
- City Council: /RSSFeed.aspx?ModID=65&CID=City-Council-2
- Main Calendar: /RSSFeed.aspx?ModID=58&CID=Main-Calendar-14
- All News: /RSSFeed.aspx?ModID=1&CID=All-newsflash.xml
"""

import re
from datetime import datetime
from typing import Optional
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import feedparser
import httpx

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


# CivicPlus module IDs
CIVICPLUS_MODULES = {
    "agenda": 65,
    "calendar": 58,
    "alerts": 63,
    "news": 1,
    "blog": 51,
    "jobs": 66,
}

# Known category IDs for Twinsburg
TWINSBURG_AGENDA_CATEGORIES = {
    "city_council": "City-Council-2",
    "planning_commission": "Planning-Commission-4",
    "architecture_review_board": "Architecture-Review-Board-5",
    "board_of_zoning_appeals": "Board-of-Zoning-Appeals-3",
    "parks_recreation_commission": "Parks-Recreation-Commission-7",
    "finance_committee": "Finance-Committee-8",
    "safety_committee": "Safety-Committee-13",
    "environmental_commission": "Environmental-Commission-22",
    "civil_service_commission": "Civil-Service-Commission-9",
    "capital_improvement_board": "Capital-Improvement-Board-11",
    "jedi_committee": "Justice-Equity-Diversity-Inclusion-Commi-23",
    "public_hearing": "Public-Hearing-14",
    "all": "All-0",
}

TWINSBURG_CALENDAR_CATEGORIES = {
    "main": "Main-Calendar-14",
    "parks_recreation": "Parks-Recreation-22",
    "fitness_center": "Fitness-Center-24",
    "community_events": "Community-Events-25",
    "meetings": "Meetings-23",
    "around_town": "Around-Town-31",
    "all": "All-calendar.xml",
}


class CivicPlusRssDriver(BaseDriver):
    """
    Driver for CivicPlus RSS feeds.
    
    Uses RSS feeds instead of HTML scraping for more reliable data extraction.
    Best for: getting recent updates, monitoring for new content.
    
    Expected params in YAML config:
        base_url: Base URL of the city website
        module: Type of content (agenda, calendar, alerts, news)
        categories: List of category keys or custom CID values
        
    Example config:
        - name: "City Council RSS"
          driver: "civic_plus_rss"
          params:
            base_url: "https://www.mytwinsburg.com"
            module: "agenda"
            categories:
              - "city_council"
              - "finance_committee"
    """
    
    # Regex to extract date from agenda titles
    DATE_PATTERN = re.compile(
        r"(?:Agenda for\s+)?(\w+\s+\d{1,2},?\s+\d{4})",
        re.IGNORECASE
    )

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch events and documents from CivicPlus RSS feeds."""
        events: list[Event] = []
        documents: list[Document] = []

        base_url = self.params.get("base_url", "").rstrip("/")
        module = self.params.get("module", "agenda")
        categories = self.params.get("categories", ["all"])
        fetch_full_details = self.params.get("fetch_full_details", False)
        
        if not base_url:
            raise ValueError("Missing required param: base_url")

        # Get module ID
        mod_id = CIVICPLUS_MODULES.get(module)
        if not mod_id:
            raise ValueError(f"Unknown module: {module}. Available: {list(CIVICPLUS_MODULES.keys())}")

        # Process each category
        for category_key in categories:
            # Resolve category key to CID
            cid = self._resolve_category(module, category_key)
            
            # Build RSS URL
            rss_url = f"{base_url}/RSSFeed.aspx?ModID={mod_id}&CID={cid}"
            
            self.log_info(f"Fetching RSS feed: {rss_url}")

            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30.0,
                headers={"User-Agent": "CivicCommons/1.0 (civic data aggregator)"}
            ) as client:
                await self.rate_limit_delay()
                response = await client.get(rss_url)
                response.raise_for_status()

                # Parse the feed
                feed = feedparser.parse(response.text)

                if feed.bozo and feed.bozo_exception:
                    self.log_warning(f"Feed parse warning: {feed.bozo_exception}")

                # Process entries based on module type
                for entry in feed.entries:
                    if module == "agenda":
                        event, docs = self._parse_agenda_entry(entry, category_key)
                        if event:
                            # Attach documents directly to event
                            event.documents.extend(docs)
                            events.append(event)
                            documents.extend(docs)
                    elif module == "calendar":
                        event = self._parse_calendar_entry(entry)
                        if event:
                            # Optionally fetch full details from the event page
                            if fetch_full_details and event.source_url:
                                event, event_docs = await self._fetch_full_event_details(
                                    client, base_url, event
                                )
                                # Attach documents directly to event
                                event.documents.extend(event_docs)
                                documents.extend(event_docs)
                            events.append(event)
                    elif module in ("news", "alerts", "blog"):
                        # These are informational, not events
                        # Could create Documents or a separate News model
                        pass

        # Deduplicate
        events = self._deduplicate_events(events)
        
        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents
    
    def _resolve_category(self, module: str, category_key: str) -> str:
        """
        Resolve a category key to a CivicPlus CID value.
        
        Args:
            module: Module type (agenda, calendar, etc.)
            category_key: Either a known key or a raw CID value
            
        Returns:
            CID value for the RSS URL
        """
        # Try known category mappings first
        if module == "agenda":
            if category_key in TWINSBURG_AGENDA_CATEGORIES:
                return TWINSBURG_AGENDA_CATEGORIES[category_key]
        elif module == "calendar":
            if category_key in TWINSBURG_CALENDAR_CATEGORIES:
                return TWINSBURG_CALENDAR_CATEGORIES[category_key]
        
        # Fall back to using the key as-is (allows custom CID values)
        return category_key
    
    def _parse_agenda_entry(
        self, entry, category: str
    ) -> tuple[Optional[Event], list[Document]]:
        """
        Parse an agenda RSS entry.
        
        Returns tuple of (Event, list of Documents).
        """
        documents: list[Document] = []
        
        try:
            title = entry.get("title", "").strip()
            if not title:
                return None, documents
            
            # Extract date from title
            starts_at = self._extract_date_from_title(title)
            if not starts_at:
                # Fall back to RSS published date
                starts_at = self._extract_date(entry)
            
            if not starts_at:
                self.log_debug(f"Could not parse date for: {title}")
                return None, documents
            
            # Clean up title
            meeting_title = self._clean_meeting_title(title, category)
            
            # Get source URL
            source_url = entry.get("link", "")
            
            # Determine event type
            event_type = self._infer_event_type(title)
            
            # Create event
            event = Event(
                title=meeting_title,
                starts_at=starts_at,
                event_type=event_type,
                source_url=source_url,
                external_id=entry.get("id", source_url),
            )
            
            # Check for document links in the entry
            # CivicPlus RSS often includes PDF links in content/summary
            content = entry.get("summary", "") or entry.get("description", "")
            doc_links = self._extract_document_links(content, source_url)
            
            for doc_url, doc_type in doc_links:
                doc = Document(
                    title=f"{meeting_title} - {doc_type.value.replace('_', ' ').title()}",
                    doc_type=doc_type,
                    original_url=doc_url,
                    meeting_date=starts_at,
                )
                documents.append(doc)
            
            # Also check enclosures
            for enclosure in entry.get("enclosures", []):
                doc_url = enclosure.get("href", "")
                if doc_url and ".pdf" in doc_url.lower():
                    doc = Document(
                        title=f"{meeting_title} - Attachment",
                        doc_type=DocumentType.OTHER,
                        original_url=doc_url,
                        meeting_date=starts_at,
                    )
                    documents.append(doc)
            
            return event, documents
            
        except Exception as e:
            self.log_error(f"Error parsing agenda entry: {e}")
            return None, documents
    
    def _parse_calendar_entry(self, entry) -> Optional[Event]:
        """Parse a calendar RSS entry."""
        try:
            title = entry.get("title", "").strip()
            if not title:
                return None
            
            # Skip cancelled events
            if "cancelled" in title.lower() or "canceled" in title.lower():
                return None
            
            # Extract the ACTUAL event date (not pubDate which is when it was posted)
            # CivicPlus calendar RSS has custom namespace fields with actual event info
            starts_at = self._extract_calendar_event_date(entry)
            
            if not starts_at:
                # Fall back to pubDate only if we couldn't get event date
                starts_at = self._extract_date(entry)
                
            if not starts_at:
                return None
            
            # Get description - but strip out the date/time/location that we've already parsed
            description = entry.get("summary", "") or entry.get("description", "")
            if description:
                description = self._clean_calendar_description(description)
            
            # Extract location from custom field or description
            location = self._extract_calendar_location(entry)
            
            # Get source URL  
            source_url = entry.get("link", "")
            
            # Determine event type
            event_type = self._infer_event_type(title + " " + (description or ""))
            
            return Event(
                title=title,
                starts_at=starts_at,
                description=description,
                location=location,
                event_type=event_type,
                source_url=source_url,
                external_id=entry.get("id", source_url),
            )
            
        except Exception as e:
            self.log_error(f"Error parsing calendar entry: {e}")
            return None
    
    async def _fetch_full_event_details(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        event: Event,
    ) -> tuple[Event, list[Document]]:
        """
        Fetch full event details from the event page.
        
        Enhances the RSS-parsed event with full description and documents.
        
        Args:
            client: HTTP client
            base_url: Base URL for resolving relative links
            event: Event object from RSS parsing
            
        Returns:
            Tuple of (enhanced event, list of documents)
        """
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        documents = []
        
        try:
            await self.rate_limit_delay()
            response = await client.get(event.source_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Get full description from itemprop="description"
            desc_elem = soup.select_one('[itemprop="description"]')
            if desc_elem:
                # Preserve some formatting
                for br in desc_elem.find_all("br"):
                    br.replace_with("\n")
                for p in desc_elem.find_all("p"):
                    p.insert_after("\n\n")
                
                full_description = desc_elem.get_text(separator=" ", strip=True)
                
                # Clean up whitespace
                full_description = re.sub(r'\n\s*\n', '\n\n', full_description)
                full_description = re.sub(r' +', ' ', full_description)
                
                # Limit length
                if len(full_description) > 2000:
                    full_description = full_description[:2000]
                    last_period = full_description.rfind('.')
                    if last_period > 1500:
                        full_description = full_description[:last_period + 1]
                
                if full_description and len(full_description) > len(event.description or ""):
                    event.description = full_description.strip()
            
            # Get better location if available
            if not event.location or len(event.location) < 20:
                location_parts = []
                
                # Facility/location name
                name_elem = soup.select_one('[itemprop="location"] [itemprop="name"]')
                if name_elem:
                    name = name_elem.get_text(strip=True)
                    if name:
                        location_parts.append(name)
                
                # Street address
                street_elem = soup.select_one('[itemprop="streetAddress"]')
                if street_elem:
                    location_parts.append(street_elem.get_text(strip=True))
                
                # City, state, zip
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
                    event.location = ", ".join(location_parts)
            
            # Extract documents from itemprop="documents"
            doc_list = soup.select_one('[itemprop="documents"]')
            if doc_list:
                for link in doc_list.select('a[href]'):
                    href = link.get('href', '')
                    if not href:
                        continue
                    
                    full_url = urljoin(base_url, href)
                    doc_title = link.get_text(strip=True)
                    
                    if doc_title:
                        documents.append(Document(
                            title=doc_title,
                            doc_type=DocumentType.ATTACHMENT,
                            original_url=full_url,
                        ))
            
            # Also look for other document links
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
            
            return event, documents
            
        except Exception as e:
            self.log_warning(f"Could not fetch full details for {event.title}: {e}")
            return event, documents
    
    def _extract_calendar_event_date(self, entry) -> Optional[datetime]:
        """
        Extract actual event date from CivicPlus calendar RSS entry.
        
        CivicPlus uses custom namespace fields:
        - calendarEvent:EventDates: "December 14, 2025"
        - calendarEvent:EventTimes: "09:00 AM - 11:59 PM"
        
        Also falls back to parsing from description HTML.
        """
        event_date = None
        event_time = None
        
        # Try custom namespace fields (feedparser normalizes these)
        # Look for fields like 'calendarevent_eventdates', 'calendarEvent_EventDates', etc.
        for key in entry.keys():
            key_lower = key.lower().replace("-", "_").replace(":", "_")
            if "eventdate" in key_lower:
                event_date = entry.get(key, "").strip()
            elif "eventtime" in key_lower:
                event_time = entry.get(key, "").strip()
        
        # If we found the date from custom fields
        if event_date:
            return self._parse_calendar_date_time(event_date, event_time)
        
        # Fall back to parsing from description HTML
        description = entry.get("description", "") or entry.get("summary", "")
        if description:
            # Look for "Event date: December 14, 2025"
            date_match = re.search(
                r"Event date:\s*</strong>\s*(\w+ \d{1,2},? \d{4})",
                description, re.IGNORECASE
            )
            if date_match:
                event_date = date_match.group(1)
                
            # Look for "Event Time: 09:00 AM - 11:59 PM"
            time_match = re.search(
                r"Event Time:\s*</strong>\s*(\d{1,2}:\d{2}\s*[AP]M)",
                description, re.IGNORECASE
            )
            if time_match:
                event_time = time_match.group(1)
            
            if event_date:
                return self._parse_calendar_date_time(event_date, event_time)
        
        return None
    
    def _parse_calendar_date_time(
        self, date_str: str, time_str: Optional[str] = None
    ) -> Optional[datetime]:
        """Parse date and optional time strings into datetime."""
        if not date_str:
            return None
            
        date_str = date_str.strip()
        
        # Parse the date
        date_formats = [
            "%B %d, %Y",    # December 14, 2025
            "%B %d %Y",     # December 14 2025
            "%b %d, %Y",    # Dec 14, 2025
            "%b %d %Y",     # Dec 14 2025
            "%m/%d/%Y",     # 12/14/2025
        ]
        
        parsed_date = None
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        
        if not parsed_date:
            return None
        
        # Try to add time if available
        if time_str:
            time_str = time_str.strip()
            # Handle time ranges like "09:00 AM - 11:59 PM" - take start time
            if " - " in time_str:
                time_str = time_str.split(" - ")[0].strip()
            
            time_formats = [
                "%I:%M %p",     # 09:00 AM
                "%I:%M%p",      # 09:00AM
                "%H:%M",        # 09:00
            ]
            
            for fmt in time_formats:
                try:
                    parsed_time = datetime.strptime(time_str, fmt)
                    return parsed_date.replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute
                    )
                except ValueError:
                    continue
        
        return parsed_date
    
    def _extract_calendar_location(self, entry) -> Optional[str]:
        """Extract location from calendar entry."""
        # Try custom namespace field
        for key in entry.keys():
            key_lower = key.lower().replace("-", "_").replace(":", "_")
            if "location" in key_lower:
                loc = entry.get(key, "").strip()
                if loc:
                    return loc
        
        # Fall back to parsing from description
        description = entry.get("description", "") or entry.get("summary", "")
        if description:
            loc_match = re.search(
                r"Location:\s*</strong>\s*(?:<br>)?\s*(.+?)(?:<br>|</|$)",
                description, re.IGNORECASE
            )
            if loc_match:
                loc = self._strip_html(loc_match.group(1)).strip()
                if loc:
                    return loc
        
        return None
    
    def _clean_calendar_description(self, description: str) -> str:
        """
        Clean calendar description by removing the structured date/time/location
        that we've already parsed into separate fields.
        """
        if not description:
            return ""
        
        # Strip HTML first
        text = self._strip_html(description)
        
        # Remove the standard CivicPlus header info we've already extracted
        patterns = [
            r"Event date:\s*\w+ \d{1,2},? \d{4}\s*",
            r"Event Time:\s*\d{1,2}:\d{2}\s*[AP]M.*?(?=Location:|$)",
            r"Location:\s*.+?(?=\n|$)",
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        
        return text.strip()[:500] if text.strip() else ""
    
    def _extract_date_from_title(self, title: str) -> Optional[datetime]:
        """Extract date from an agenda title."""
        match = self.DATE_PATTERN.search(title)
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
    
    def _extract_date(self, entry) -> Optional[datetime]:
        """Extract date from feed entry metadata."""
        # Try structured date fields
        date_fields = ["published_parsed", "updated_parsed", "created_parsed"]
        
        for field in date_fields:
            parsed = entry.get(field)
            if parsed:
                try:
                    return datetime(*parsed[:6])
                except (TypeError, ValueError):
                    continue
        
        # Try string date fields
        string_fields = ["published", "updated", "created"]
        for field in string_fields:
            date_str = entry.get(field)
            if date_str:
                try:
                    return parsedate_to_datetime(date_str)
                except (TypeError, ValueError):
                    continue
        
        return None
    
    def _clean_meeting_title(self, raw_title: str, category: str) -> str:
        """Clean up a meeting title."""
        # Remove "Agenda for DATE" prefix
        title = self.DATE_PATTERN.sub("", raw_title)
        
        # Remove common suffixes
        title = re.sub(r"\s*\(PDF\).*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*Opens in new window.*$", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s*-\s*AMENDED.*$", "", title, flags=re.IGNORECASE)
        
        # Clean whitespace
        title = " ".join(title.split())
        
        if len(title) < 5:
            # Use category name as fallback
            title = category.replace("_", " ").title() + " Meeting"
        
        return title.strip()
    
    def _infer_event_type(self, text: str) -> EventType:
        """Infer event type from text."""
        text_lower = text.lower()
        
        if "hearing" in text_lower:
            return EventType.HEARING
        elif "work session" in text_lower or "workshop" in text_lower:
            return EventType.WORKSHOP
        elif any(kw in text_lower for kw in ["program", "class", "course", "camp"]):
            return EventType.PROGRAM
        elif any(kw in text_lower for kw in ["festival", "celebration", "parade"]):
            return EventType.COMMUNITY
        else:
            return EventType.MEETING
    
    def _extract_document_links(
        self, content: str, base_url: str
    ) -> list[tuple[str, DocumentType]]:
        """
        Extract document links from RSS content.
        
        Returns list of (url, doc_type) tuples.
        """
        links = []
        
        # Look for PDF links
        pdf_pattern = re.compile(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', re.IGNORECASE)
        for match in pdf_pattern.finditer(content):
            url = match.group(1)
            if not url.startswith("http"):
                url = base_url.rsplit("/", 1)[0] + "/" + url.lstrip("/")
            
            # Determine type from URL
            url_lower = url.lower()
            if "agenda" in url_lower:
                doc_type = DocumentType.AGENDA
            elif "minute" in url_lower:
                doc_type = DocumentType.MINUTES
            elif "packet" in url_lower:
                doc_type = DocumentType.PACKET
            else:
                doc_type = DocumentType.OTHER
            
            links.append((url, doc_type))
        
        return links
    
    def _strip_html(self, html: str) -> str:
        """Remove HTML tags from a string."""
        # Simple HTML tag removal
        clean = re.sub(r'<[^>]+>', '', html)
        # Decode common entities
        clean = clean.replace("&nbsp;", " ")
        clean = clean.replace("&amp;", "&")
        clean = clean.replace("&lt;", "<")
        clean = clean.replace("&gt;", ">")
        clean = clean.replace("&quot;", '"')
        # Clean whitespace
        return " ".join(clean.split())
    
    def _deduplicate_events(self, events: list[Event]) -> list[Event]:
        """Remove duplicate events."""
        seen = set()
        unique = []
        
        for event in events:
            key = (event.title, event.starts_at.date() if event.starts_at else None)
            if key not in seen:
                seen.add(key)
                unique.append(event)
        
        return unique
