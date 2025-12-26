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

import feedparser
import httpx

from .base import BaseDriver
from .civicplus_utils import (
    CIVICPLUS_MODULES,
    DATE_PATTERN,
    extract_date_from_title,
    infer_event_type,
    clean_meeting_title,
    strip_html,
)
from models import Event, Document, EventType, DocumentType


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

        mod_id = CIVICPLUS_MODULES.get(module)
        if not mod_id:
            raise ValueError(f"Unknown module: {module}. Available: {list(CIVICPLUS_MODULES.keys())}")

        for category_key in categories:
            cid = self._resolve_category(module, category_key)
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

                feed = feedparser.parse(response.text)

                if feed.bozo and feed.bozo_exception:
                    self.log_warning(f"Feed parse warning: {feed.bozo_exception}")

                for entry in feed.entries:
                    if module == "agenda":
                        event, docs = self._parse_agenda_entry(entry, category_key)
                        if event:
                            event.documents.extend(docs)
                            events.append(event)
                            documents.extend(docs)
                    elif module == "calendar":
                        event = self._parse_calendar_entry(entry)
                        if event:
                            if fetch_full_details and event.source_url:
                                event, event_docs = await self._fetch_full_event_details(
                                    client, base_url, event
                                )
                                event.documents.extend(event_docs)
                                documents.extend(event_docs)
                            events.append(event)
                    # news, alerts, blog are informational, not events

        events = self._deduplicate_events(events)
        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents
    
    def _resolve_category(self, module: str, category_key: str) -> str:
        """Resolve a category key to a CivicPlus CID value.
        
        Category mappings should be provided in config params:
        - agenda_categories: dict mapping keys to CIDs
        - calendar_categories: dict mapping keys to CIDs
        
        If no mapping exists, the category_key is used as-is (allows raw CIDs).
        """
        if module == "agenda":
            agenda_cats = self.params.get("agenda_categories", {})
            if category_key in agenda_cats:
                return agenda_cats[category_key]
        elif module == "calendar":
            calendar_cats = self.params.get("calendar_categories", {})
            if category_key in calendar_cats:
                return calendar_cats[category_key]
        
        return category_key  # Use as-is for custom CID values
    
    # =========================================================================
    # Agenda Parsing
    # =========================================================================
    
    def _parse_agenda_entry(
        self, entry, category: str
    ) -> tuple[Optional[Event], list[Document]]:
        """Parse an agenda RSS entry."""
        documents: list[Document] = []
        
        try:
            title = entry.get("title", "").strip()
            if not title:
                return None, documents
            
            # Extract date from title (using shared utility)
            starts_at = extract_date_from_title(title)
            if not starts_at:
                starts_at = self._extract_date_from_entry(entry)
            
            if not starts_at:
                self.log_debug(f"Could not parse date for: {title}")
                return None, documents
            
            meeting_title = clean_meeting_title(title, category)
            source_url = entry.get("link", "")
            event_type = infer_event_type(title)
            
            event = Event(
                title=meeting_title,
                starts_at=starts_at,
                event_type=event_type,
                source_url=source_url,
                external_id=entry.get("id", source_url),
            )
            
            # Check for document links in the entry
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
    
    # =========================================================================
    # Calendar Parsing
    # =========================================================================
    
    def _parse_calendar_entry(self, entry) -> Optional[Event]:
        """Parse a calendar RSS entry."""
        try:
            title = entry.get("title", "").strip()
            if not title:
                return None
            
            if "cancelled" in title.lower() or "canceled" in title.lower():
                return None
            
            # Extract actual event date (not pubDate)
            starts_at = self._extract_calendar_event_date(entry)
            if not starts_at:
                starts_at = self._extract_date_from_entry(entry)
                
            if not starts_at:
                return None
            
            description = entry.get("summary", "") or entry.get("description", "")
            if description:
                description = self._clean_calendar_description(description)
            
            location = self._extract_calendar_location(entry)
            source_url = entry.get("link", "")
            event_type = infer_event_type(title + " " + (description or ""))
            
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
    
    def _extract_calendar_event_date(self, entry) -> Optional[datetime]:
        """
        Extract actual event date from CivicPlus calendar RSS entry.
        
        CivicPlus uses custom namespace fields:
        - calendarEvent:EventDates: "December 14, 2025"
        - calendarEvent:EventTimes: "09:00 AM - 11:59 PM"
        """
        event_date = None
        event_time = None
        
        for key in entry.keys():
            key_lower = key.lower().replace("-", "_").replace(":", "_")
            if "eventdate" in key_lower:
                event_date = entry.get(key, "").strip()
            elif "eventtime" in key_lower:
                event_time = entry.get(key, "").strip()
        
        if event_date:
            return self._parse_calendar_date_time(event_date, event_time)
        
        # Fall back to parsing from description HTML
        description = entry.get("description", "") or entry.get("summary", "")
        if description:
            date_match = re.search(
                r"Event date:\s*</strong>\s*(\w+ \d{1,2},? \d{4})",
                description, re.IGNORECASE
            )
            if date_match:
                event_date = date_match.group(1)
                
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
        
        if time_str:
            time_str = time_str.strip()
            if " - " in time_str:
                time_str = time_str.split(" - ")[0].strip()
            
            time_formats = ["%I:%M %p", "%I:%M%p", "%H:%M"]
            
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
        for key in entry.keys():
            key_lower = key.lower().replace("-", "_").replace(":", "_")
            if "location" in key_lower:
                loc = entry.get(key, "").strip()
                if loc:
                    return loc
        
        description = entry.get("description", "") or entry.get("summary", "")
        if description:
            loc_match = re.search(
                r"Location:\s*</strong>\s*(?:<br>)?\s*(.+?)(?:<br>|</|$)",
                description, re.IGNORECASE
            )
            if loc_match:
                loc = strip_html(loc_match.group(1)).strip()
                if loc:
                    return loc
        
        return None
    
    def _clean_calendar_description(self, description: str) -> str:
        """Clean calendar description by removing parsed date/time/location."""
        if not description:
            return ""
        
        text = strip_html(description)
        
        patterns = [
            r"Event date:\s*\w+ \d{1,2},? \d{4}\s*",
            r"Event Time:\s*\d{1,2}:\d{2}\s*[AP]M.*?(?=Location:|$)",
            r"Location:\s*.+?(?=\n|$)",
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        
        return text.strip()[:500] if text.strip() else ""
    
    # =========================================================================
    # Full Event Details
    # =========================================================================
    
    async def _fetch_full_event_details(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        event: Event,
    ) -> tuple[Event, list[Document]]:
        """Fetch full event details from the event page."""
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        documents = []
        
        try:
            await self.rate_limit_delay()
            response = await client.get(event.source_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Get full description
            desc_elem = soup.select_one('[itemprop="description"]')
            if desc_elem:
                for br in desc_elem.find_all("br"):
                    br.replace_with("\n")
                for p in desc_elem.find_all("p"):
                    p.insert_after("\n\n")
                
                full_description = desc_elem.get_text(separator=" ", strip=True)
                full_description = re.sub(r'\n\s*\n', '\n\n', full_description)
                full_description = re.sub(r' +', ' ', full_description)
                
                if len(full_description) > 2000:
                    full_description = full_description[:2000]
                    last_period = full_description.rfind('.')
                    if last_period > 1500:
                        full_description = full_description[:last_period + 1]
                
                if full_description and len(full_description) > len(event.description or ""):
                    event.description = full_description.strip()
            
            # Get location if not already set
            if not event.location or len(event.location) < 20:
                location_parts = []
                
                name_elem = soup.select_one('[itemprop="location"] [itemprop="name"]')
                if name_elem:
                    name = name_elem.get_text(strip=True)
                    if name:
                        location_parts.append(name)
                
                street_elem = soup.select_one('[itemprop="streetAddress"]')
                if street_elem:
                    location_parts.append(street_elem.get_text(strip=True))
                
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
            
            # Extract documents
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
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _extract_date_from_entry(self, entry) -> Optional[datetime]:
        """Extract date from feed entry metadata."""
        date_fields = ["published_parsed", "updated_parsed", "created_parsed"]
        
        for field in date_fields:
            parsed = entry.get(field)
            if parsed:
                try:
                    return datetime(*parsed[:6])
                except (TypeError, ValueError):
                    continue
        
        string_fields = ["published", "updated", "created"]
        for field in string_fields:
            date_str = entry.get(field)
            if date_str:
                try:
                    return parsedate_to_datetime(date_str)
                except (TypeError, ValueError):
                    continue
        
        return None
    
    def _extract_document_links(
        self, content: str, base_url: str
    ) -> list[tuple[str, DocumentType]]:
        """Extract document links from RSS content."""
        links = []
        
        pdf_pattern = re.compile(r'href=["\']([^"\']*\.pdf[^"\']*)["\']', re.IGNORECASE)
        for match in pdf_pattern.finditer(content):
            url = match.group(1)
            if not url.startswith("http"):
                url = base_url.rsplit("/", 1)[0] + "/" + url.lstrip("/")
            
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

