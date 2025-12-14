"""
Purpose: Driver for LibCal/Springshare library event systems
Dependencies: httpx for HTTP requests
Consumed by: Worker for public library events
Side effects: HTTP requests to LibCal API
"""

from datetime import datetime
from typing import Optional

import httpx

from .base import BaseDriver
from models import Event, EventType, Document


class LibCalDriver(BaseDriver):
    """
    Driver for LibCal (Springshare) library event management.
    
    LibCal provides a JSON API for library events. Many public libraries
    use this system.
    
    Expected params in YAML config:
        library_id: LibCal library identifier
        api_url: Optional custom API URL (defaults to LibCal)
        
    Example config:
        - name: "Public Library"
          driver: "libcal"
          params:
            library_id: "twinsburg"
    """

    # Default LibCal API base
    DEFAULT_API_BASE = "https://api3.libcal.com"

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch events from LibCal API."""
        events: list[Event] = []
        documents: list[Document] = []  # LibCal typically doesn't have docs

        library_id = self.params.get("library_id")
        if not library_id:
            raise ValueError("Missing required param: library_id")

        api_base = self.params.get("api_url", self.DEFAULT_API_BASE)

        self.log_info(f"Fetching LibCal events for: {library_id}")

        async with httpx.AsyncClient() as client:
            # LibCal public API endpoint
            # Note: Some LibCal instances may require authentication
            url = f"{api_base}/api_events.php"
            
            await self.rate_limit_delay()
            response = await client.get(
                url,
                params={
                    "iid": library_id,
                    "limit": 100,  # Get up to 100 events
                    "cal_id": "",  # All calendars
                },
            )

            # LibCal may return HTML on error, check content type
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                self.log_error(f"Unexpected response type: {content_type}")
                # Try alternate API format
                events = await self._try_alternate_api(client, library_id)
                return events, documents

            response.raise_for_status()
            data = response.json()

            # Parse events from response
            if isinstance(data, dict):
                # Some LibCal responses wrap in an object
                event_list = data.get("events", [])
            elif isinstance(data, list):
                event_list = data
            else:
                event_list = []

            for item in event_list:
                event = self._parse_event(item)
                if event:
                    events.append(event)

        self.log_info(f"Found {len(events)} events")
        return events, documents

    async def _try_alternate_api(
        self,
        client: httpx.AsyncClient,
        library_id: str,
    ) -> list[Event]:
        """Try alternate LibCal API format (for newer versions)."""
        events: list[Event] = []
        
        # Some libraries use a different URL structure
        alternate_urls = [
            f"https://{library_id}.libcal.com/ajax/events",
            f"https://libcal.{library_id}.org/ajax/events",
        ]

        for url in alternate_urls:
            try:
                await self.rate_limit_delay()
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get("events", []):
                        event = self._parse_event(item)
                        if event:
                            events.append(event)
                    if events:
                        break
            except Exception:
                continue

        return events

    def _parse_event(self, item: dict) -> Optional[Event]:
        """Parse a LibCal event item into an Event."""
        try:
            # LibCal event structure
            title = item.get("title", "").strip()
            if not title:
                return None

            # Parse dates
            start_str = item.get("start") or item.get("startdt")
            if not start_str:
                return None

            starts_at = self._parse_datetime(start_str)
            if not starts_at:
                return None

            ends_at = None
            end_str = item.get("end") or item.get("enddt")
            if end_str:
                ends_at = self._parse_datetime(end_str)

            # Location
            location = item.get("location", {})
            if isinstance(location, dict):
                location_str = location.get("name", "")
            else:
                location_str = str(location) if location else ""

            # Description
            description = item.get("description", "")

            # URL
            source_url = item.get("url", "")

            # All day flag
            all_day = item.get("allday", False)

            # Virtual info
            is_virtual = item.get("online", False)
            virtual_url = item.get("online_url", "")

            return Event(
                title=title,
                description=description,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=location_str,
                is_virtual=is_virtual,
                virtual_url=virtual_url,
                source_url=source_url,
                event_type=EventType.PROGRAM,
                external_id=str(item.get("id", "")),
            )

        except Exception as e:
            self.log_error(f"Error parsing LibCal event: {e}")
            return None

    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        """Parse LibCal datetime formats."""
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",     # ISO with timezone
            "%Y-%m-%dT%H:%M:%S",       # ISO without timezone
            "%Y-%m-%d %H:%M:%S",       # Space separated
            "%Y-%m-%d",                # Date only
            "%m/%d/%Y %I:%M %p",       # US format with time
            "%m/%d/%Y",                # US format
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        return None
