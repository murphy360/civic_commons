"""
Purpose: Driver for CivicPlus Document Center pages (legislation, ordinances, etc.)
Dependencies: Playwright for browser automation (JS rendering), BeautifulSoup for HTML parsing
Consumed by: Worker for legislation document scraping
Side effects: HTTP requests to CivicPlus Document Center

CivicPlus DocumentCenter Structure:
- Folders organize documents by category/year (e.g., "2025 Legislation")
- Each folder has paginated document lists (25 per page by default)
- Documents are PDFs with URLs like: /DocumentCenter/View/{docId}/{slug}
- Folder URLs: /DocumentCenter/Index/{folderId}
- Pagination is handled via JavaScript (React/Material-UI components)
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


class CivicPlusDocumentCenterDriver(BaseDriver):
    """
    Driver for CivicPlus Document Center pages.
    
    Scrapes legislation, ordinances, and other documents from CivicPlus
    Document Center folders. Handles JavaScript-rendered pagination.
    
    Expected params in YAML config:
        base_url: Base URL of the city website
        folder_id: Numeric ID of the folder to scrape
        folder_name: Human-readable name for the folder (for logging)
        document_type: Type of documents (default: "legislation")
        
    Example config:
        - name: "2025 Legislation"
          driver: "civicplus_document_center"
          params:
            base_url: "https://www.mytwinsburg.com"
            folder_id: 433
            folder_name: "2025 Legislation"
            document_type: "legislation"
    """
    
    # Pattern to extract document ID from URL
    DOC_ID_PATTERN = re.compile(r"/DocumentCenter/View/(\d+)")
    
    # Pattern to extract ordinance number from filename (e.g., "07-25", "101-25")
    ORDINANCE_PATTERN = re.compile(r"^(\d{1,3})-(\d{2})\s+(.+)")

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch documents from CivicPlus Document Center folder."""
        events: list[Event] = []
        documents: list[Document] = []

        base_url = self.params.get("base_url", "").rstrip("/")
        folder_id = self.params.get("folder_id")
        folder_name = self.params.get("folder_name", f"Folder {folder_id}")
        document_type_str = self.params.get("document_type", "legislation")
        
        if not base_url:
            raise ValueError("Missing required param: base_url")
        if not folder_id:
            raise ValueError("Missing required param: folder_id")

        folder_url = f"{base_url}/DocumentCenter/Index/{folder_id}"
        
        self.log_info(f"Fetching Document Center folder: {folder_name} ({folder_url})")

        # Use Playwright for JavaScript-rendered pagination
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="CivicCommons/1.0 (civic data aggregator)"
            )
            page = await context.new_page()
            
            try:
                # Navigate to folder
                await page.goto(folder_url, wait_until="networkidle", timeout=30000)
                
                # Wait for document list to load
                await self._wait_for_documents(page)
                
                # Get all documents across all pages
                all_doc_data = await self._scrape_all_pages(page, base_url)
                
                self.log_info(f"Found {len(all_doc_data)} documents in {folder_name}")
                
                # Convert to Document objects
                for doc_data in all_doc_data:
                    doc = self._create_document(
                        doc_data=doc_data,
                        base_url=base_url,
                        folder_name=folder_name,
                        document_type_str=document_type_str
                    )
                    if doc:
                        documents.append(doc)
                        
            except PlaywrightTimeout as e:
                self.log_warning(f"Timeout loading folder {folder_id}: {e}")
            except Exception as e:
                self.log_error(f"Error scraping folder {folder_id}: {e}")
                raise
            finally:
                await browser.close()

        self.log_info(f"Returning {len(documents)} documents from {folder_name}")
        return events, documents

    async def _wait_for_documents(self, page: Page, timeout: int = 10000) -> None:
        """Wait for the document list to be rendered."""
        try:
            # Wait for either document links or "No Documents" message
            await page.wait_for_selector(
                "a[href*='/DocumentCenter/View/'], h4:has-text('No Documents')",
                timeout=timeout
            )
        except PlaywrightTimeout:
            self.log_warning("Document list did not load within timeout")

    async def _scrape_all_pages(self, page: Page, base_url: str) -> list[dict]:
        """Scrape documents from all pages."""
        all_docs = []
        page_num = 1
        
        while True:
            self.log_info(f"Scraping page {page_num}...")
            
            # Get documents on current page
            page_docs = await self._scrape_current_page(page, base_url)
            
            if not page_docs:
                self.log_info(f"No documents found on page {page_num}, stopping")
                break
                
            all_docs.extend(page_docs)
            self.log_info(f"Found {len(page_docs)} documents on page {page_num}")
            
            # Check if there's a next page
            has_next = await self._go_to_next_page(page)
            
            if not has_next:
                self.log_info("No more pages")
                break
                
            page_num += 1
            
            # Safety limit
            if page_num > 20:
                self.log_warning("Reached page limit (20), stopping")
                break
                
            # Wait for new page to load
            await self._wait_for_documents(page)
            
        return all_docs

    async def _scrape_current_page(self, page: Page, base_url: str) -> list[dict]:
        """Extract document data from the current page."""
        docs = []
        
        # Get page HTML
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        # Find all document links
        doc_links = soup.find_all("a", href=re.compile(r"/DocumentCenter/View/\d+"))
        
        for link in doc_links:
            href = link.get("href", "")
            title = link.get_text(strip=True)
            
            # Skip empty titles or navigation links
            if not title or title.lower() in ["open", "download", "view"]:
                continue
            
            # Extract document ID
            doc_id_match = self.DOC_ID_PATTERN.search(href)
            if not doc_id_match:
                continue
                
            doc_id = doc_id_match.group(1)
            
            # Build full URL
            full_url = urljoin(base_url, href)
            
            # Try to find associated date (usually in a sibling or parent element)
            date_str = self._find_document_date(link)
            
            docs.append({
                "id": doc_id,
                "title": title,
                "url": full_url,
                "date_str": date_str
            })
        
        return docs

    def _find_document_date(self, link_elem) -> Optional[str]:
        """Try to find the date associated with a document link."""
        # CivicPlus Document Center often has date in a span with class containing "secondary"
        # or in a sibling/parent element
        
        # Check parent list item
        parent_li = link_elem.find_parent("li")
        if parent_li:
            # Look for date pattern in the list item text
            text = parent_li.get_text()
            # Try common date formats
            date_patterns = [
                r"(\d{1,2}/\d{1,2}/\d{4})",  # MM/DD/YYYY
                r"(\w+ \d{1,2}, \d{4})",  # Month DD, YYYY
            ]
            for pattern in date_patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(1)
        
        return None

    async def _go_to_next_page(self, page: Page) -> bool:
        """Try to navigate to the next page. Returns True if successful."""
        try:
            # Look for "Next Page" button - CivicPlus uses title attribute
            # The button has title="Next Page" and aria-label="Next Page"
            next_button = await page.query_selector(
                'button[title="Next Page"], '
                'button[aria-label="Next Page"]'
            )
            
            if next_button:
                # Check if button is disabled (disabled attribute present or "true")
                is_disabled = await next_button.get_attribute("disabled")
                if is_disabled is not None and is_disabled != "":
                    self.log_info("Next Page button is disabled")
                    return False
                
                # Also check if the button is actually visible/enabled
                is_visible = await next_button.is_visible()
                is_enabled = await next_button.is_enabled()
                
                if not is_visible or not is_enabled:
                    self.log_info(f"Next Page button not clickable (visible={is_visible}, enabled={is_enabled})")
                    return False
                    
                self.log_info("Clicking Next Page button...")
                await next_button.click()
                
                # Wait for page transition and new content to load
                await page.wait_for_timeout(1500)  # 1.5 second delay for content
                return True
                
            self.log_info("No Next Page button found")
            return False
            
        except Exception as e:
            self.log_warning(f"Error navigating to next page: {e}")
            return False

    def _create_document(
        self,
        doc_data: dict,
        base_url: str,
        folder_name: str,
        document_type_str: str
    ) -> Optional[Document]:
        """Create a Document object from scraped data."""
        title = doc_data.get("title", "")
        url = doc_data.get("url", "")
        date_str = doc_data.get("date_str")
        
        if not title or not url:
            return None
        
        # Parse ordinance number from title
        ordinance_match = self.ORDINANCE_PATTERN.match(title)
        ordinance_number = None
        ordinance_year = None
        clean_title = title
        
        if ordinance_match:
            ordinance_number = f"{ordinance_match.group(1)}-{ordinance_match.group(2)}"
            ordinance_year = f"20{ordinance_match.group(2)}"
            clean_title = ordinance_match.group(3).strip()
        
        # Determine document type
        doc_type = DocumentType.OTHER
        if document_type_str == "legislation":
            if "ordinance" in title.lower() or "ord" in title.lower():
                doc_type = DocumentType.OTHER  # Could add ORDINANCE type
            elif "resolution" in title.lower() or "res" in title.lower():
                doc_type = DocumentType.OTHER  # Could add RESOLUTION type
            else:
                doc_type = DocumentType.OTHER
        
        # Parse date if available
        published_at = None
        if date_str:
            try:
                # Try common formats
                for fmt in ["%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"]:
                    try:
                        published_at = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
            except Exception:
                pass
        
        # Create a descriptive title
        display_title = title
        if ordinance_number and clean_title != title:
            display_title = f"{ordinance_number}: {clean_title}"
        
        return Document(
            original_url=url,
            external_id=doc_data.get("id"),
            doc_type=doc_type,
            title=display_title,
            published_at=published_at,
            metadata={
                "folder_name": folder_name,
                "document_id": doc_data.get("id"),
                "ordinance_number": ordinance_number,
                "ordinance_year": ordinance_year,
                "original_title": title,
                "source_name": self.source_name
            }
        )
