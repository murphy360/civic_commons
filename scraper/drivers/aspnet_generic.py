"""
Purpose: Driver for ASP.NET-based municipal websites requiring JavaScript rendering
Dependencies: Playwright for browser automation
Consumed by: Worker for school boards, complex government sites
Side effects: Launches headless browser, HTTP requests
"""

from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


class AspNetGenericDriver(BaseDriver):
    """
    Driver for ASP.NET sites that require JavaScript rendering.
    
    Uses Playwright to render pages that rely on JavaScript for content.
    More resource-intensive than simple HTTP drivers.
    
    Expected params in YAML config:
        url: Full URL to the meetings page
        
    Example config:
        - name: "School Board"
          driver: "aspnet_generic"
          params:
            url: "https://www.twinsburg.k12.oh.us/meetingsandagendas.aspx"
    """

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch meetings using Playwright browser automation."""
        events: list[Event] = []
        documents: list[Document] = []

        url = self.params.get("url")
        if not url:
            raise ValueError("Missing required param: url")

        self.log_info(f"Launching browser for: {url}")

        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=True)
            
            try:
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = await context.new_page()

                # Navigate to page
                await self.rate_limit_delay()
                await page.goto(url, wait_until="networkidle")

                # Wait for content to load
                await page.wait_for_timeout(2000)  # 2 second buffer

                # Parse the page
                events, documents = await self._parse_page(page, url)

            finally:
                await browser.close()

        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents

    async def _parse_page(
        self,
        page: Page,
        base_url: str,
    ) -> tuple[list[Event], list[Document]]:
        """
        Parse meetings from the rendered page.
        
        ASP.NET sites vary widely, so this uses generic selectors.
        May need customization for specific sites.
        """
        events: list[Event] = []
        documents: list[Document] = []

        # Try common ASP.NET patterns
        # GridView tables
        rows = await page.query_selector_all(
            "table[id*='GridView'] tr, "
            "table[id*='gv'] tr, "
            ".meeting-list tr, "
            ".meetings-table tbody tr"
        )

        for row in rows:
            # Skip header rows
            header = await row.query_selector("th")
            if header:
                continue

            event, docs = await self._parse_row(row, base_url)
            if event:
                events.append(event)
                documents.extend(docs)

        # If no table found, try list-based layouts
        if not events:
            items = await page.query_selector_all(
                ".meeting-item, "
                ".event-item, "
                "[class*='meeting'], "
                "[class*='agenda']"
            )
            
            for item in items:
                event, docs = await self._parse_item(item, base_url)
                if event:
                    events.append(event)
                    documents.extend(docs)

        return events, documents

    async def _parse_row(
        self,
        row,
        base_url: str,
    ) -> tuple[Optional[Event], list[Document]]:
        """Parse a table row into an event and documents."""
        documents: list[Document] = []
        
        try:
            cells = await row.query_selector_all("td")
            if len(cells) < 2:
                return None, documents

            # First cell usually has date
            date_text = await cells[0].inner_text()
            starts_at = self._parse_date(date_text.strip())

            if not starts_at:
                return None, documents

            # Second cell usually has title/type
            title_text = await cells[1].inner_text()
            title = title_text.strip() or f"Meeting - {date_text.strip()}"

            event = Event(
                title=title,
                starts_at=starts_at,
                event_type=EventType.MEETING,
                source_url=base_url,
            )

            # Find PDF links in the row
            links = await row.query_selector_all("a[href*='.pdf'], a[href*='download']")
            for link in links:
                href = await link.get_attribute("href")
                if not href:
                    continue

                link_text = await link.inner_text()
                doc_url = urljoin(base_url, href)
                doc_type = self._infer_doc_type(link_text)

                doc = Document(
                    title=f"{title} - {doc_type.value.title()}",
                    doc_type=doc_type,
                    original_url=doc_url,
                    meeting_date=starts_at,
                )
                documents.append(doc)

            return event, documents

        except Exception as e:
            self.log_error(f"Error parsing row: {e}")
            return None, documents

    async def _parse_item(
        self,
        item,
        base_url: str,
    ) -> tuple[Optional[Event], list[Document]]:
        """Parse a list item into an event and documents."""
        # Similar to _parse_row but for non-table layouts
        documents: list[Document] = []
        
        try:
            # Look for date element
            date_elem = await item.query_selector(
                ".date, .meeting-date, [class*='date'], time"
            )
            if not date_elem:
                return None, documents

            date_text = await date_elem.inner_text()
            starts_at = self._parse_date(date_text.strip())

            if not starts_at:
                return None, documents

            # Look for title
            title_elem = await item.query_selector(
                ".title, .meeting-title, h3, h4, strong"
            )
            title = "Meeting"
            if title_elem:
                title = await title_elem.inner_text()
                title = title.strip()

            event = Event(
                title=title,
                starts_at=starts_at,
                event_type=EventType.MEETING,
                source_url=base_url,
            )

            # Find document links
            links = await item.query_selector_all("a[href*='.pdf']")
            for link in links:
                href = await link.get_attribute("href")
                if href:
                    link_text = await link.inner_text()
                    doc = Document(
                        title=f"{title} - {link_text.strip()}",
                        doc_type=self._infer_doc_type(link_text),
                        original_url=urljoin(base_url, href),
                        meeting_date=starts_at,
                    )
                    documents.append(doc)

            return event, documents

        except Exception as e:
            self.log_error(f"Error parsing item: {e}")
            return None, documents

    def _parse_date(self, date_text: str) -> Optional[datetime]:
        """Parse common date formats."""
        formats = [
            "%B %d, %Y",
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%Y-%m-%d",
            "%b %d, %Y",
            "%m/%d/%y",
        ]

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
        return DocumentType.OTHER
