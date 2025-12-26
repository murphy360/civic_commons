"""
Purpose: Driver for TCSD (Twinsburg City School District) Board of Education Agendas/Minutes
Dependencies: httpx, BeautifulSoup
Consumed by: Worker for school board documents
Side effects: HTTP requests to fetch page and PDFs
"""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


class TCSDagendasDriver(BaseDriver):
    """
    Driver for TCSD Board of Education Agendas and Minutes page.
    
    The page at twinsburg.k12.oh.us/agendasandminutes.aspx has a simple structure:
    - Sections organized by year ("Minutes 2025", "Minutes 2024", etc.)
    - Each section contains links to PDF documents
    - Link text contains the date and meeting type
    
    Expected params in YAML config:
        url: Full URL to the agendas page
        
    Example config:
        - name: "TCSD Board of Education"
          driver: "tcsd_agendas"
          params:
            url: "https://www.twinsburg.k12.oh.us/agendasandminutes.aspx"
    """

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch agendas and minutes from the TCSD website."""
        events: list[Event] = []
        documents: list[Document] = []

        url = self.params.get("url")
        if not url:
            raise ValueError("Missing required param: url")

        self.log_info(f"Fetching TCSD agendas from: {url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            await self.rate_limit_delay()
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find all PDF links on the page
            links = soup.find_all("a", href=lambda x: x and ".pdf" in x.lower())
            
            for link in links:
                href = link.get("href")
                link_text = link.get_text(strip=True)
                
                if not href or not link_text:
                    continue
                
                # Parse the link to extract date and document type
                doc = self._parse_link(link_text, href, url)
                if doc:
                    documents.append(doc)

        self.log_info(f"Found {len(documents)} documents")
        return events, documents

    def _parse_link(
        self,
        link_text: str,
        href: str,
        base_url: str
    ) -> Optional[Document]:
        """
        Parse a link into a Document.
        
        Link text formats observed:
        - "December 17, 2025 Finance Committee Meeting"
        - "December 15, 2025 - Special Meeting"
        - "November 19, 2025 Regular Meeting"
        - "January 4, 2012 Organizational"
        """
        try:
            # Build full URL
            doc_url = urljoin(base_url, href)
            
            # Try to extract date from the link text
            meeting_date = self._parse_date_from_text(link_text)
            
            # Determine document type from text AND URL
            doc_type = self._infer_doc_type(link_text, href)
            
            # Clean up title
            title = self._clean_title(link_text, doc_type)
            
            return Document(
                title=title,
                doc_type=doc_type,
                original_url=doc_url,
                meeting_date=meeting_date,
            )
            
        except Exception as e:
            self.log_error(f"Error parsing link '{link_text}': {e}")
            return None

    def _parse_date_from_text(self, text: str) -> Optional[datetime]:
        """
        Extract date from link text.
        
        Examples:
        - "December 17, 2025 Finance Committee Meeting" -> 2025-12-17
        - "January 4, 2012 Organizational" -> 2012-01-04
        """
        # Pattern for "Month Day, Year" at the start
        date_patterns = [
            # Full month name: "December 17, 2025"
            (r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", "%B %d %Y"),
            # Abbreviated month: "Dec 17, 2025"  
            (r"^([A-Za-z]{3})\s+(\d{1,2}),?\s+(\d{4})", "%b %d %Y"),
            # Also try month/day/year format just in case
            (r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", None),
        ]
        
        for pattern, date_format in date_patterns:
            match = re.match(pattern, text.strip())
            if match:
                if date_format:
                    # Remove any commas and extra spaces
                    date_str = f"{match.group(1)} {match.group(2)} {match.group(3)}"
                    try:
                        return datetime.strptime(date_str, date_format)
                    except ValueError:
                        continue
                else:
                    # Handle numeric date format
                    month, day, year = match.groups()
                    if len(year) == 2:
                        year = "20" + year if int(year) < 50 else "19" + year
                    try:
                        return datetime(int(year), int(month), int(day))
                    except ValueError:
                        continue
        
        return None

    def _infer_doc_type(self, text: str, url: str = "") -> DocumentType:
        """
        Infer document type from link text and URL.
        
        The page structure shows:
        - "Agendas" section contains agenda documents
        - "Minutes" sections contain minutes documents
        
        Also checks URL for hints like "Agenda" or "Minutes" in filename.
        """
        text_lower = text.lower()
        url_lower = url.lower()
        
        # Check both text and URL for agenda/minutes indicators
        # Check agenda first (more specific)
        if "agenda" in text_lower or "agenda" in url_lower:
            return DocumentType.AGENDA
        elif "minute" in text_lower or "mins" in url_lower or "minute" in url_lower:
            return DocumentType.MINUTES
        
        # Default based on typical patterns - most documents are minutes
        # unless they're in an Agendas section (but we can't detect section in this context)
        return DocumentType.MINUTES

    def _clean_title(self, text: str, doc_type: DocumentType) -> str:
        """
        Create a clean title for the document.
        
        Input: "December 17, 2025 Finance Committee Meeting"
        Output: "TCSD BOE Finance Committee Meeting - Agenda" (if agenda) or
                "TCSD BOE Finance Committee Meeting - Minutes" (if minutes)
        """
        # Remove the date from the beginning
        # Pattern matches: Month Day, Year or Month Day Year
        cleaned = re.sub(
            r"^[A-Za-z]+\s+\d{1,2},?\s+\d{4}\s*[-–]?\s*",
            "",
            text.strip()
        )
        
        # If nothing left after removing date, use a generic title
        if not cleaned or len(cleaned) < 3:
            cleaned = "Meeting"
            
        # Add document type suffix and prefix
        type_suffix = doc_type.value.title()  # "Agenda" or "Minutes"
        
        # Check if the title already contains the type
        if type_suffix.lower() not in cleaned.lower():
            return f"TCSD BOE {cleaned} - {type_suffix}"
        
        return f"TCSD BOE {cleaned}"

