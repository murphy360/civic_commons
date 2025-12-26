"""
Purpose: Driver for RSS/Atom feeds - universal fallback for most sites
Dependencies: httpx for HTTP, feedparser for RSS parsing
Consumed by: Worker for blogs, historical societies, simple event feeds
Side effects: HTTP requests to RSS feed
"""

from datetime import datetime
from typing import Optional
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from .base import BaseDriver
from models import Event, Document, EventType


class RssDriver(BaseDriver):
    """
    Driver for RSS and Atom feeds.
    
    Universal fallback driver that works with any standard RSS/Atom feed.
    Good for: blogs, news, event calendars with RSS output.
    
    Expected params in YAML config:
        feed_url: URL of the RSS/Atom feed
        
    Example config:
        - name: "Historical Society"
          driver: "rss"
          params:
            feed_url: "https://twinsburghistoricalsociety.org/events/feed"
    """

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch events from RSS feed."""
        events: list[Event] = []
        documents: list[Document] = []

        feed_url = self.params.get("feed_url")
        if not feed_url:
            raise ValueError("Missing required param: feed_url")

        self.log_info(f"Fetching RSS feed: {feed_url}")

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/rss+xml, application/xml, application/atom+xml, text/xml, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            }
        ) as client:
            await self.rate_limit_delay()
            response = await client.get(feed_url)
            response.raise_for_status()

            # Parse the feed
            feed = feedparser.parse(response.text)

            if feed.bozo and feed.bozo_exception:
                self.log_error(f"Feed parse warning: {feed.bozo_exception}")

            # Process entries
            for entry in feed.entries:
                event = self._parse_entry(entry)
                if event:
                    events.append(event)

                    # Check for enclosures (attached documents)
                    for enclosure in entry.get("enclosures", []):
                        if enclosure.get("type", "").startswith("application/"):
                            doc = Document(
                                title=f"{event.title} - Attachment",
                                original_url=enclosure.get("href", ""),
                            )
                            documents.append(doc)

        self.log_info(f"Found {len(events)} events, {len(documents)} documents")
        return events, documents

    def _parse_entry(self, entry) -> Optional[Event]:
        """Parse a feed entry into an Event."""
        try:
            # Get title
            title = entry.get("title", "").strip()
            if not title:
                return None

            # Get date - try multiple fields
            starts_at = self._extract_date(entry)
            if not starts_at:
                # Use current time if no date found
                starts_at = datetime.now()

            # Get description
            description = None
            if "summary" in entry:
                description = entry.summary
            elif "description" in entry:
                description = entry.description
            elif "content" in entry:
                # Atom feeds use content
                content = entry.content[0] if entry.content else {}
                description = content.get("value", "")

            # Clean HTML from description
            if description:
                description = self._strip_html(description)

            # Get link
            source_url = entry.get("link", "")

            # Determine event type from content
            event_type = self._infer_event_type(title, description or "")

            return Event(
                title=title,
                description=description,
                starts_at=starts_at,
                event_type=event_type,
                source_url=source_url,
                external_id=entry.get("id", entry.get("link", "")),
            )

        except Exception as e:
            self.log_error(f"Error parsing entry: {e}")
            return None

    def _extract_date(self, entry) -> Optional[datetime]:
        """Extract date from feed entry, trying multiple fields."""
        # Try structured date fields first
        date_fields = [
            "published_parsed",
            "updated_parsed",
            "created_parsed",
        ]

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

    def _strip_html(self, html: str) -> str:
        """Remove HTML tags from string."""
        import re
        # Simple HTML stripping - could use BeautifulSoup for complex cases
        clean = re.sub(r"<[^>]+>", "", html)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def _infer_event_type(self, title: str, description: str) -> EventType:
        """Infer event type from title and description."""
        text = f"{title} {description}".lower()

        if any(word in text for word in ["meeting", "session", "board"]):
            return EventType.MEETING
        elif any(word in text for word in ["hearing", "public hearing"]):
            return EventType.HEARING
        elif any(word in text for word in ["workshop", "work session"]):
            return EventType.WORKSHOP
        elif any(word in text for word in ["class", "program", "lesson"]):
            return EventType.PROGRAM
        elif any(word in text for word in ["deadline", "due date", "last day"]):
            return EventType.DEADLINE
        else:
            return EventType.COMMUNITY

