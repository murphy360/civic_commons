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
from .civicplus_utils import (
    DATE_PATTERN,
    extract_date_from_title,
    extract_date_from_compressed,
    extract_date_from_url,
    infer_event_type,
    infer_doc_type,
    is_document_url,
    clean_meeting_title,
)
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

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch meetings and documents from CivicPlus agenda center."""
        events: list[Event] = []
        documents: list[Document] = []
        previous_versions_urls: list[tuple[str, str, datetime]] = []

        base_url = self.params.get("base_url", "").rstrip("/")
        categories_filter = self.params.get("categories", [])
        use_browser = self.params.get("use_browser", True)
        
        if not base_url:
            raise ValueError("Missing required param: base_url")

        agenda_url = f"{base_url}/AgendaCenter"
        self.log_info(f"Fetching agenda center: {agenda_url}")

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
        
        categories = self._find_categories(soup, categories_filter)
        self.log_info(f"Found {len(categories)} categories to process")

        for category_name, category_elem in categories:
            cat_events, cat_docs, cat_prev_urls = self._parse_category_table(
                base_url=base_url,
                category_name=category_name,
                category_elem=category_elem,
            )
            events.extend(cat_events)
            documents.extend(cat_docs)
            previous_versions_urls.extend(cat_prev_urls)

        if previous_versions_urls:
            self.log_info(f"Fetching {len(previous_versions_urls)} PreviousVersions pages")
            prev_docs = await self._fetch_previous_versions(base_url, previous_versions_urls)
            documents.extend(prev_docs)

        documents = await self._fix_youtube_video_dates(documents)
        events = self._deduplicate_events(events)
        
        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents
    
    def _find_categories(
        self, soup: BeautifulSoup, filter_names: list[str]
    ) -> list[tuple[str, Tag]]:
        """Find all category sections in the agenda center."""
        categories = []
        
        # Pattern 1: h2 headers followed by span sections
        h2_headers = soup.select("h2")
        
        for h2 in h2_headers:
            cat_name = h2.get_text(strip=True)
            
            if len(cat_name) < 3 or cat_name.lower() in ["search", "download", "tools", "agenda center"]:
                continue
            
            if filter_names:
                if not any(f.lower() in cat_name.lower() for f in filter_names):
                    continue
            
            next_sibling = h2.find_next_sibling()
            if next_sibling and next_sibling.name == "span":
                if next_sibling.select('a[href*="ViewFile"]') or next_sibling.select("table"):
                    categories.append((cat_name, next_sibling))
                    self.log_debug(f"Found category '{cat_name}' with span section")
            else:
                next_table = h2.find_next("table")
                if next_table and next_table.select('a[href*="ViewFile"]'):
                    categories.append((cat_name, next_table))
                    self.log_debug(f"Found category '{cat_name}' with table fallback")
        
        # Pattern 2: Tables with preceding headers
        if not categories:
            tables = soup.select("table")
            seen_tables = set()
            
            for table in tables:
                if id(table) in seen_tables:
                    continue
                seen_tables.add(id(table))
                
                prev = table.find_previous(["h2", "h3", "h4"])
                if prev:
                    cat_name = prev.get_text(strip=True)
                    if len(cat_name) < 3 or cat_name.lower() in ["search", "download", "tools"]:
                        continue
                    
                    if filter_names:
                        if not any(f.lower() in cat_name.lower() for f in filter_names):
                            continue
                    
                    categories.append((cat_name, table))
        
        # Pattern 3: Content pattern fallback
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
        """Parse all meeting rows from a category's table."""
        events: list[Event] = []
        documents: list[Document] = []
        previous_versions_urls: list[tuple[str, str, datetime]] = []
        
        if category_elem.name == "table":
            rows = category_elem.select("tr")
        else:
            rows = category_elem.select("tr")
        
        agenda_rows = [
            row for row in rows 
            if row.select('a[href*="ViewFile"]') or row.select('a[href*="youtu"]')
        ]
        
        self.log_info(f"Category '{category_name}': found {len(agenda_rows)} agenda rows")
        
        for row in agenda_rows:
            event, docs, prev_urls = self._parse_agenda_row(base_url, category_name, row)
            if event:
                events.append(event)
                documents.extend(docs)
                previous_versions_urls.extend(prev_urls)
        
        return events, documents, previous_versions_urls
    
    def _parse_agenda_row(
        self,
        base_url: str,
        category_name: str,
        row: Tag,
    ) -> tuple[Optional[Event], list[Document], list[tuple[str, str, datetime]]]:
        """Parse a single agenda row."""
        documents: list[Document] = []
        previous_versions_urls: list[tuple[str, str, datetime]] = []
        
        try:
            row_text = row.get_text(" ", strip=True)
            links = row.select("a")
            if not links:
                return None, documents, previous_versions_urls
            
            starts_at = self._extract_date_from_row(row)
            
            agenda_link = None
            agenda_text = None
            
            for link in links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                
                if not href or "Download" in text or href.startswith("javascript"):
                    continue
                
                if "agenda" in text.lower() or "ViewFile/Agenda" in href:
                    agenda_link = link
                    agenda_text = text
                    break
                
                if not agenda_link and len(text) > 5:
                    agenda_link = link
                    agenda_text = text
            
            if not agenda_text:
                return None, documents, previous_versions_urls
            
            if not starts_at:
                starts_at = extract_date_from_title(agenda_text)
            
            if not starts_at:
                self.log_info(f"Could not parse date from row: '{row_text[:100]}'")
                return None, documents, previous_versions_urls
            
            meeting_title = clean_meeting_title(agenda_text, category_name)
            event_type = infer_event_type(agenda_text)
            source_url = base_url + "/AgendaCenter"
            
            event = Event(
                title=meeting_title,
                starts_at=starts_at,
                event_type=event_type,
                source_url=source_url,
                location="Council Chambers",
            )
            
            for link in links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                
                if not href or href.startswith("javascript") or "Download" in text:
                    continue
                
                doc_url = urljoin(base_url, href)
                
                if "/AgendaCenter/PreviousVersions/" in doc_url:
                    previous_versions_urls.append((doc_url, meeting_title, starts_at))
                    continue
                
                if not is_document_url(doc_url):
                    continue
                
                doc_type = infer_doc_type(text, href)
                url_date = extract_date_from_url(doc_url)
                doc_date = url_date or starts_at
                
                doc = Document(
                    title=f"{meeting_title} - {doc_type.value.replace('_', ' ').title()}",
                    doc_type=doc_type,
                    original_url=doc_url,
                    meeting_date=doc_date,
                    published_at=doc_date,
                )
                documents.append(doc)
            
            return event, documents, previous_versions_urls
            
        except Exception as e:
            self.log_error(f"Error parsing agenda row: {e}")
            return None, documents, previous_versions_urls
    
    def _extract_date_from_row(self, row: Tag) -> Optional[datetime]:
        """Extract date from any part of an agenda row."""
        cells = row.select("td")
        
        for cell in cells:
            cell_text = cell.get_text(strip=True)
            
            date = extract_date_from_compressed(cell_text)
            if date:
                return date
            
            date = extract_date_from_title(cell_text)
            if date:
                return date
        
        row_text = row.get_text(" ", strip=True)
        return extract_date_from_compressed(row_text)

    async def _extract_date_from_youtube(self, url: str) -> tuple[Optional[datetime], Optional[str]]:
        """Extract date and title from a YouTube video page."""
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15.0,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            ) as client:
                await self.rate_limit_delay()
                response = await client.get(url)
                response.raise_for_status()
                
                title_match = re.search(r'<title>([^<]+)</title>', response.text)
                if not title_match:
                    return None, None
                
                raw_title = title_match.group(1)
                title = re.sub(r'\s*-\s*YouTube\s*$', '', raw_title)
                date = extract_date_from_title(title)
                
                if date:
                    self.log_debug(f"Extracted date {date.date()} from YouTube title: {title}")
                    return date, title
                
                return None, title
                
        except Exception as e:
            self.log_debug(f"Could not fetch YouTube title for {url}: {e}")
            return None, None
    
    async def _fetch_previous_versions(
        self,
        base_url: str,
        previous_versions_urls: list[tuple[str, str, datetime]],
    ) -> list[Document]:
        """Fetch PreviousVersions pages and extract all linked documents."""
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
                    links = soup.select("a[href]")
                    
                    for link in links:
                        href = link.get("href", "")
                        text = link.get_text(strip=True)
                        
                        if not href or href.startswith("javascript"):
                            continue
                        
                        doc_url = urljoin(base_url, href)
                        
                        if not is_document_url(doc_url):
                            continue
                        
                        doc_type = infer_doc_type(text, href)
                        url_date = extract_date_from_url(doc_url)
                        doc_date = url_date or meeting_date
                        
                        doc = Document(
                            title=f"{meeting_title} - {doc_type.value.replace('_', ' ').title()}",
                            doc_type=doc_type,
                            original_url=doc_url,
                            meeting_date=doc_date,
                            published_at=doc_date,
                        )
                        documents.append(doc)
                        
                except httpx.HTTPStatusError as e:
                    self.log_error(f"HTTP error fetching {prev_url}: {e}")
                except Exception as e:
                    self.log_error(f"Error fetching PreviousVersions page {prev_url}: {e}")
        
        self.log_info(f"Found {len(documents)} documents from PreviousVersions pages")
        return documents

    async def _fix_youtube_video_dates(self, documents: list[Document]) -> list[Document]:
        """Fix dates for YouTube videos by fetching their actual titles."""
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
                doc.meeting_date = video_date
                doc.published_at = video_date
                if video_title:
                    doc.title = f"{video_title} - Video"
        
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

    async def _fetch_with_browser(self, url: str, categories_filter: list[str]) -> str:
        """Use Playwright to fetch page with JavaScript rendering."""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent="CivicCommons/1.0 (civic data aggregator)"
                )
                page = await context.new_page()
                
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(2000)
                
                # Expand category sections
                category_headers = await page.query_selector_all(
                    'span[class*="catHeader"], div[class*="catHeader"], '
                    'a[onclick*="toggleCat"], span[onclick*="toggle"]'
                )
                
                for header in category_headers:
                    try:
                        header_text = await header.text_content()
                        if categories_filter:
                            if not any(f.lower() in (header_text or "").lower() 
                                      for f in categories_filter):
                                continue
                        await header.click()
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass
                
                # Click triangles/arrows
                triangles = await page.query_selector_all(
                    'span.ui-icon-triangle-1-e, span[class*="collapsed"], '
                    'img[src*="arrow"], span[class*="toggle"]'
                )
                
                for triangle in triangles:
                    try:
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
                
                await page.wait_for_timeout(1000)
                return await page.content()
                
            finally:
                await browser.close()

