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
        previous_versions_urls: list[tuple[str, str, datetime]] = []  # (url, meeting_title, date)

        base_url = self.params.get("base_url", "").rstrip("/")
        categories_filter = self.params.get("categories", [])
        use_browser = self.params.get("use_browser", True)  # Default to browser for JS rendering
        
        if not base_url:
            raise ValueError("Missing required param: base_url")

        # Construct agenda center URL
        agenda_url = f"{base_url}/AgendaCenter"
        
        self.log_info(f"Fetching agenda center: {agenda_url}")

        # Use Playwright for JavaScript-heavy CivicPlus pages
        if use_browser:
            html_content = await self._fetch_with_browser(agenda_url, categories_filter)
            soup = BeautifulSoup(html_content, "html.parser")
        else:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=30.0,
                headers={"User-Agent": "CivicCommons/1.0 (civic data aggregator)"}
            ) as client:
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
                
                # Parse the agenda table for this category
                cat_events, cat_docs, cat_prev_urls = self._parse_category_table(
                    base_url=base_url,
                    category_name=category_name,
                    category_elem=category_elem,
                )
                events.extend(cat_events)
                documents.extend(cat_docs)
                previous_versions_urls.extend(cat_prev_urls)

        # Fetch PreviousVersions pages to get archived agendas, minutes, media
        if previous_versions_urls:
            self.log_info(f"Fetching {len(previous_versions_urls)} PreviousVersions pages")
            prev_docs = await self._fetch_previous_versions(base_url, previous_versions_urls)
            documents.extend(prev_docs)

        # Fix dates for YouTube videos by fetching their titles
        documents = await self._fix_youtube_video_dates(documents)

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
        
        # CivicPlus AgendaCenter structure:
        # Each category has an <h2> header followed by a <span id="sectionN"> containing the content
        # The span contains tables with agenda rows
        
        # Pattern 1: Look for h2 headers followed by span sections
        # This is the standard CivicPlus AgendaCenter layout
        h2_headers = soup.select("h2")
        
        for h2 in h2_headers:
            cat_name = h2.get_text(strip=True)
            
            # Skip empty or generic headers
            if len(cat_name) < 3 or cat_name.lower() in ["search", "download", "tools", "agenda center"]:
                continue
            
            # Filter by category names if specified
            if filter_names:
                if not any(f.lower() in cat_name.lower() for f in filter_names):
                    continue
            
            # Find the section element that follows this h2
            # CivicPlus uses <span id="sectionN"> after each h2
            next_sibling = h2.find_next_sibling()
            if next_sibling and next_sibling.name == "span":
                # Check if this span has agenda content (tables with ViewFile links)
                if next_sibling.select('a[href*="ViewFile"]') or next_sibling.select("table"):
                    categories.append((cat_name, next_sibling))
                    self.log_debug(f"Found category '{cat_name}' with span section")
            else:
                # Fallback: look for the next table element
                next_table = h2.find_next("table")
                if next_table and next_table.select('a[href*="ViewFile"]'):
                    categories.append((cat_name, next_table))
                    self.log_debug(f"Found category '{cat_name}' with table fallback")
        
        # Pattern 2: If no h2 categories found, try tables with preceding headers
        if not categories:
            tables = soup.select("table")
            seen_tables = set()
            
            for table in tables:
                if id(table) in seen_tables:
                    continue
                seen_tables.add(id(table))
                
                # Look for the category name in a preceding header element
                prev = table.find_previous(["h2", "h3", "h4"])
                if prev:
                    cat_name = prev.get_text(strip=True)
                    if len(cat_name) < 3 or cat_name.lower() in ["search", "download", "tools"]:
                        continue
                    
                    if filter_names:
                        if not any(f.lower() in cat_name.lower() for f in filter_names):
                            continue
                    
                    categories.append((cat_name, table))
        
        # Pattern 3: Look for sections by content pattern as last resort
        if not categories:
            agenda_rows = soup.select("tr")
            current_category = "General"
            
            for row in agenda_rows:
                agenda_link = row.select_one('a[href*="AgendaCenter"], a[href*="ViewFile"]')
                if agenda_link:
                    if current_category not in [c[0] for c in categories]:
                        categories.append((current_category, row.parent))
        
        return categories

    def _parse_category_table(
        self,
        base_url: str,
        category_name: str,
        category_elem: Tag,
    ) -> tuple[list[Event], list[Document], list[tuple[str, str, datetime]]]:
        """
        Parse all meeting rows from a category's table.
        
        Returns tuple of (events, documents, previous_versions_urls).
        previous_versions_urls is a list of (url, meeting_title, date) tuples.
        """
        events: list[Event] = []
        documents: list[Document] = []
        previous_versions_urls: list[tuple[str, str, datetime]] = []
        
        # Find all rows in this table/section
        # If category_elem is a span, find all tr elements within it (including nested tables)
        # If it's a table, get direct tr children
        if category_elem.name == "table":
            rows = category_elem.select("tr")
        else:
            # For span or other containers, find all tr elements anywhere inside
            rows = category_elem.select("tr")
        
        # Filter to only rows that contain agenda links (skip header rows, etc.)
        agenda_rows = [
            row for row in rows 
            if row.select('a[href*="ViewFile"]') or row.select('a[href*="youtu"]')
        ]
        
        self.log_info(f"Category '{category_name}': found {len(agenda_rows)} agenda rows (from {len(rows)} total rows)")
        
        for row in agenda_rows:
            event, docs, prev_urls = self._parse_agenda_row(base_url, category_name, row)
            if event:
                events.append(event)
                documents.extend(docs)
                previous_versions_urls.extend(prev_urls)
            else:
                # Log first few characters of row for debugging
                row_text = row.get_text(strip=True)[:100] if row else "None"
                self.log_debug(f"No event parsed from row: {row_text}")
        
        return events, documents, previous_versions_urls
    
    def _parse_agenda_row(
        self,
        base_url: str,
        category_name: str,
        row: Tag,
    ) -> tuple[Optional[Event], list[Document], list[tuple[str, str, datetime]]]:
        """
        Parse a single agenda row.
        
        CivicPlus rows typically have:
        - Column 1: Date (e.g. "Dec2, 2025")
        - Column 2: Agenda link with title
        - Column 3: Minutes link (if available)
        - Column 4: Media/Video link (if available)
        - Column 5: Download dropdown
        
        Returns tuple of (Event or None, list of Documents, list of PreviousVersions URL tuples).
        PreviousVersions tuples are (url, meeting_title, date).
        """
        documents: list[Document] = []
        previous_versions_urls: list[tuple[str, str, datetime]] = []
        
        try:
            # Get all text from the row for date extraction
            row_text = row.get_text(" ", strip=True)
            
            # Find all links in this row
            links = row.select("a")
            if not links:
                return None, documents, previous_versions_urls
            
            # First, try to extract date from anywhere in the row
            # CivicPlus puts dates in a separate cell, like "Dec2, 2025" or "Nov17, 2025"
            starts_at = self._extract_date_from_row(row)
            
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
                if not agenda_link and len(text) > 5:
                    agenda_link = link
                    agenda_text = text
            
            if not agenda_text:
                return None, documents, previous_versions_urls
            
            # If we couldn't get date from row, try the link text
            if not starts_at:
                starts_at = self._extract_date_from_title(agenda_text)
            
            if not starts_at:
                self.log_info(f"Could not parse date from row: '{row_text[:100]}'")
                return None, documents, previous_versions_urls
            
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
                
                # Collect PreviousVersions URLs for later processing
                if "/AgendaCenter/PreviousVersions/" in doc_url:
                    self.log_debug(f"Found PreviousVersions URL: {doc_url}")
                    previous_versions_urls.append((doc_url, meeting_title, starts_at))
                    continue
                
                # Skip other navigation pages
                if not self._is_document_url(doc_url):
                    self.log_debug(f"Skipping non-document URL: {doc_url}")
                    continue
                
                # Determine document type
                doc_type = self._infer_doc_type(text, href)
                
                # Extract date from URL if available (more reliable)
                url_date = self._extract_date_from_url(doc_url)
                doc_date = url_date or starts_at
                
                # Create document
                doc = Document(
                    title=f"{meeting_title} - {doc_type.value.replace('_', ' ').title()}",
                    doc_type=doc_type,
                    original_url=doc_url,
                    meeting_date=doc_date,
                    published_at=doc_date,  # Also set published_at for display
                )
                documents.append(doc)
            
            return event, documents, previous_versions_urls
            
        except Exception as e:
            self.log_error(f"Error parsing agenda row: {e}")
            return None, documents, previous_versions_urls
    
    def _extract_date_from_row(self, row: Tag) -> Optional[datetime]:
        """
        Extract date from any part of an agenda row.
        
        CivicPlus puts dates in various formats:
        - "Dec2, 2025" (compressed format in date column)
        - "Nov17, 2025"
        - "December 2, 2025" (full format)
        
        Looks in table cells and any text in the row.
        """
        # Get all table cells
        cells = row.select("td")
        
        for cell in cells:
            cell_text = cell.get_text(strip=True)
            
            # Pattern for compressed dates like "Dec2, 2025" or "Nov17, 2025"
            compressed_match = re.search(
                r"([A-Z][a-z]{2})(\d{1,2}),?\s*(\d{4})",
                cell_text
            )
            if compressed_match:
                month_abbr = compressed_match.group(1)
                day = compressed_match.group(2)
                year = compressed_match.group(3)
                try:
                    return datetime.strptime(f"{month_abbr} {day}, {year}", "%b %d, %Y")
                except ValueError:
                    continue
            
            # Also try the full date pattern
            date = self._extract_date_from_title(cell_text)
            if date:
                return date
        
        # Fall back to searching full row text
        row_text = row.get_text(" ", strip=True)
        
        # Try compressed format
        compressed_match = re.search(
            r"([A-Z][a-z]{2})(\d{1,2}),?\s*(\d{4})",
            row_text
        )
        if compressed_match:
            month_abbr = compressed_match.group(1)
            day = compressed_match.group(2)
            year = compressed_match.group(3)
            try:
                return datetime.strptime(f"{month_abbr} {day}, {year}", "%b %d, %Y")
            except ValueError:
                pass
        
        return None

    def _extract_date_from_url(self, url: str) -> Optional[datetime]:
        """
        Extract date from a CivicPlus document URL.
        
        CivicPlus URLs embed dates in MMDDYYYY format:
        - /AgendaCenter/ViewFile/Agenda/_02272025-1386 -> Feb 27, 2025
        - /AgendaCenter/ViewFile/Minutes/_12092024-1371 -> Dec 9, 2024
        
        The underscore precedes the date, and a dash follows it.
        """
        # Pattern: _MMDDYYYY-
        match = re.search(r"_(\d{2})(\d{2})(\d{4})-", url)
        if match:
            month = match.group(1)
            day = match.group(2)
            year = match.group(3)
            try:
                return datetime.strptime(f"{month}/{day}/{year}", "%m/%d/%Y")
            except ValueError:
                pass
        
        return None

    async def _extract_date_from_youtube(self, url: str) -> tuple[Optional[datetime], Optional[str]]:
        """
        Extract date and title from a YouTube video page.
        
        YouTube video titles from Twinsburg contain the meeting date:
        - "City of Twinsburg Council Meeting - January 28, 2025 - YouTube"
        - "City of Twinsburg Special Council Meeting - January 2, 2025 - YouTube"
        
        Returns:
            Tuple of (date, cleaned_title) or (None, None) if not found
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15.0,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            ) as client:
                await self.rate_limit_delay()
                response = await client.get(url)
                response.raise_for_status()
                
                # Extract title from HTML
                title_match = re.search(r'<title>([^<]+)</title>', response.text)
                if not title_match:
                    return None, None
                
                raw_title = title_match.group(1)
                # Remove " - YouTube" suffix
                title = re.sub(r'\s*-\s*YouTube\s*$', '', raw_title)
                
                # Extract date from title using the same pattern as agenda titles
                date = self._extract_date_from_title(title)
                
                if date:
                    self.log_debug(f"Extracted date {date.date()} from YouTube title: {title}")
                    return date, title
                
                return None, title
                
        except Exception as e:
            self.log_debug(f"Could not fetch YouTube title for {url}: {e}")
            return None, None

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
        
        # Check for video URLs first (YouTube, Vimeo, etc.)
        if any(video_host in href_lower for video_host in [
            'youtube.com', 'youtu.be', 'vimeo.com', 'wistia.com',
            'video', 'media', 'stream'
        ]):
            return DocumentType.VIDEO
        
        # Check URL patterns (more reliable for CivicPlus)
        if "viewfile/minutes" in href_lower:
            return DocumentType.MINUTES
        elif "viewfile/archivedagenda" in href_lower:
            return DocumentType.AGENDA  # Archived agendas are still agendas
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
    
    def _is_document_url(self, href: str) -> bool:
        """
        Check if a URL points to an actual document vs a navigation page.
        
        CivicPlus has various URL patterns:
        - /ViewFile/Agenda/_MMDDYYYY-XXX -> actual document (PDF)
        - /ViewFile/Minutes/_MMDDYYYY-XXX -> actual document (PDF)
        - /ViewFile/ArchivedAgenda/_MMDDYYYY-XXX -> actual document (PDF)
        - /PreviousVersions/_MMDDYYYY-XXX -> navigation page (skip these)
        """
        href_lower = href.lower()
        
        # Skip non-http links (tel:, mailto:, javascript:, etc.)
        if not (href_lower.startswith('http://') or href_lower.startswith('https://')):
            return False
        
        # Skip PreviousVersions pages - they're navigation, not documents
        if "/previousversions/" in href_lower:
            return False
        
        # Accept ViewFile URLs - these are actual documents
        if "/viewfile/" in href_lower:
            return True
        
        # Accept direct PDF links
        if href_lower.endswith('.pdf'):
            return True
        
        # Accept video URLs - only actual videos, not channel pages
        # Valid: youtube.com/watch?v=XXX, youtu.be/XXX, vimeo.com/123456
        # Invalid: youtube.com/channel/XXX, youtube.com (homepage), mytwinsburg.com/youtube
        if 'youtu.be/' in href_lower:
            return True  # Short YouTube URLs are always video links
        if 'youtube.com/watch' in href_lower:
            return True  # Standard YouTube video URLs
        if 'vimeo.com/' in href_lower and not href_lower.endswith('vimeo.com/'):
            # Vimeo videos have a numeric ID in the path
            return True
        
        # Reject all other URLs - they're likely navigation or external links
        return False
    
    async def _fetch_previous_versions(
        self,
        base_url: str,
        previous_versions_urls: list[tuple[str, str, datetime]],
    ) -> list[Document]:
        """
        Fetch PreviousVersions pages and extract all linked documents.
        
        PreviousVersions pages contain links to:
        - Archived agendas (/ViewFile/ArchivedAgenda/)
        - Minutes (/ViewFile/Minutes/)
        - Media/video links
        
        Args:
            base_url: Base URL of the site
            previous_versions_urls: List of (url, meeting_title, date) tuples
            
        Returns:
            List of Document objects found on the pages
        """
        documents: list[Document] = []
        
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": "CivicCommons/1.0 (civic data aggregator)"}
        ) as client:
            for prev_url, meeting_title, meeting_date in previous_versions_urls:
                try:
                    self.log_debug(f"Fetching PreviousVersions page: {prev_url}")
                    await self.rate_limit_delay()
                    response = await client.get(prev_url)
                    response.raise_for_status()
                    
                    soup = BeautifulSoup(response.text, "html.parser")
                    
                    # Find all document links on this page
                    links = soup.select("a[href]")
                    
                    for link in links:
                        href = link.get("href", "")
                        text = link.get_text(strip=True)
                        
                        # Skip empty or navigation links
                        if not href or href.startswith("javascript"):
                            continue
                        
                        # Build full URL
                        doc_url = urljoin(base_url, href)
                        
                        # Only process actual document URLs (not navigation)
                        if not self._is_document_url(doc_url):
                            continue
                        
                        # Determine document type
                        doc_type = self._infer_doc_type(text, href)
                        
                        # Extract date from URL if available (more reliable)
                        url_date = self._extract_date_from_url(doc_url)
                        doc_date = url_date or meeting_date
                        
                        # Create document
                        doc = Document(
                            title=f"{meeting_title} - {doc_type.value.replace('_', ' ').title()}",
                            doc_type=doc_type,
                            original_url=doc_url,
                            meeting_date=doc_date,
                            published_at=doc_date,
                        )
                        documents.append(doc)
                        self.log_debug(f"Found document from PreviousVersions: {doc.title}")
                        
                except httpx.HTTPStatusError as e:
                    self.log_error(f"HTTP error fetching {prev_url}: {e}")
                except Exception as e:
                    self.log_error(f"Error fetching PreviousVersions page {prev_url}: {e}")
        
        self.log_info(f"Found {len(documents)} documents from PreviousVersions pages")
        return documents

    async def _fix_youtube_video_dates(self, documents: list[Document]) -> list[Document]:
        """
        Fix dates for YouTube videos by fetching their actual titles.
        
        YouTube video titles from Twinsburg contain the meeting date:
        - "City of Twinsburg Council Meeting - January 28, 2025"
        
        This corrects videos that were assigned the wrong date during parsing.
        """
        youtube_docs = [
            doc for doc in documents 
            if doc.original_url and ('youtube.com' in doc.original_url or 'youtu.be' in doc.original_url)
        ]
        
        if not youtube_docs:
            return documents
        
        self.log_info(f"Fixing dates for {len(youtube_docs)} YouTube videos")
        
        for doc in youtube_docs:
            video_date, video_title = await self._extract_date_from_youtube(doc.original_url)
            
            if video_date:
                old_date = doc.meeting_date
                doc.meeting_date = video_date
                doc.published_at = video_date
                
                # Also update the title to use the YouTube title if available
                if video_title:
                    doc.title = f"{video_title} - Video"
                
                self.log_info(f"Fixed YouTube video date: {old_date.date() if old_date else 'None'} -> {video_date.date()} for {doc.original_url}")
        
        return documents
    
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

    async def _fetch_with_browser(
        self, 
        url: str, 
        categories_filter: list[str]
    ) -> str:
        """
        Use Playwright to fetch page with JavaScript rendering.
        
        CivicPlus Agenda Center uses JavaScript to show/hide category sections.
        We need to expand each category to get the full content.
        """
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="CivicCommons/1.0 (civic data aggregator)"
                )
                page = await context.new_page()
                
                # Navigate to the agenda center
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Wait for the page to load
                await page.wait_for_timeout(2000)
                
                # Expand all category sections by clicking on them
                # CivicPlus uses spans/triangles to expand categories
                category_headers = await page.query_selector_all(
                    'span[class*="catHeader"], div[class*="catHeader"], '
                    'a[onclick*="toggleCat"], span[onclick*="toggle"]'
                )
                
                self.log_debug(f"Found {len(category_headers)} expandable category headers")
                
                # Click each category to expand it
                for header in category_headers:
                    try:
                        header_text = await header.text_content()
                        
                        # If filtering by category, only expand matching ones
                        if categories_filter:
                            if not any(f.lower() in (header_text or "").lower() 
                                      for f in categories_filter):
                                continue
                        
                        self.log_debug(f"Expanding category: {header_text}")
                        await header.click()
                        await page.wait_for_timeout(500)  # Wait for animation
                    except Exception as e:
                        self.log_debug(f"Could not click header: {e}")
                
                # Also try clicking all triangles/arrows that indicate collapsed sections
                triangles = await page.query_selector_all(
                    'span.ui-icon-triangle-1-e, span[class*="collapsed"], '
                    'img[src*="arrow"], span[class*="toggle"]'
                )
                
                for triangle in triangles:
                    try:
                        # Check if parent contains a category we want
                        parent = await triangle.evaluate_handle('el => el.parentElement')
                        parent_text = await parent.text_content() if parent else ""
                        
                        if categories_filter:
                            if not any(f.lower() in (parent_text or "").lower() 
                                      for f in categories_filter):
                                continue
                        
                        await triangle.click()
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
                
                # Wait for content to load
                await page.wait_for_timeout(1000)
                
                # Get the full HTML content
                html = await page.content()
                
                return html
                
            finally:
                await browser.close()
