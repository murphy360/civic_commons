"""
Purpose: Template for creating new drivers - copy and customize
Dependencies: base.py, models, httpx for HTTP requests
Consumed by: Not used directly - copy to create new drivers
Side effects: HTTP requests to source website
"""

# ============================================================================
# HOW TO USE THIS TEMPLATE:
# 1. Copy this file to your_driver.py
# 2. Rename the class to YourDriverDriver
# 3. Implement the fetch() method
# 4. Register in __init__.py
# ============================================================================

import httpx

from .base import BaseDriver
from models import Event, Document, EventType, DocumentType


class TemplateDriver(BaseDriver):
    """
    Driver for [Source Type Name].
    
    Expected params in YAML config:
        base_url: Base URL of the source website
        # Add other required params here
        
    Example config:
        - name: "Example Source"
          driver: "template"
          params:
            base_url: "https://example.com"
    """

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """
        Fetch events and documents from the source.
        
        Returns:
            Tuple of (events, documents)
        """
        events: list[Event] = []
        documents: list[Document] = []

        # Get configuration params
        base_url = self.params.get("base_url")
        if not base_url:
            raise ValueError("Missing required param: base_url")

        self.log_info(f"Fetching from {base_url}")

        # Create HTTP client
        async with httpx.AsyncClient() as client:
            # Example: Fetch a page
            await self.rate_limit_delay()
            response = await client.get(f"{base_url}/events")
            response.raise_for_status()

            # TODO: Parse the response
            # html = response.text
            # soup = BeautifulSoup(html, "html.parser")
            # 
            # for item in soup.select(".event-item"):
            #     event = Event(
            #         title=item.select_one(".title").text,
            #         starts_at=parse_datetime(item.select_one(".date").text),
            #         source_url=f"{base_url}/events/{item['id']}",
            #     )
            #     events.append(event)

            pass  # Remove this when implementing

        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents


# ============================================================================
# COMMON PATTERNS
# ============================================================================

# Pattern: Parsing HTML tables
# from bs4 import BeautifulSoup
# 
# soup = BeautifulSoup(html, "html.parser")
# for row in soup.select("table.meetings tbody tr"):
#     cells = row.find_all("td")
#     event = Event(
#         title=cells[0].text.strip(),
#         starts_at=parse_date(cells[1].text.strip()),
#     )

# Pattern: Downloading PDFs
# async def download_pdf(self, client: httpx.AsyncClient, url: str) -> Document:
#     await self.rate_limit_delay()
#     response = await client.get(url)
#     response.raise_for_status()
#     
#     return Document(
#         title=url.split("/")[-1],
#         original_url=url,
#         # file_path set by pipeline after saving
#     )

# Pattern: Handling pagination
# page = 1
# while True:
#     response = await client.get(f"{base_url}/events?page={page}")
#     items = parse_items(response.text)
#     if not items:
#         break
#     events.extend(items)
#     page += 1
#     await self.rate_limit_delay()

