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
    
    LibCal provides event data via either:
    1. Legacy API at api3.libcal.com (deprecated for most libraries)
    2. Subdomain-based URLs like {library_id}.libcal.com
    
    Expected params in YAML config:
        library_id: LibCal library subdomain identifier (e.g., "twinsburglibrary")
        iid: Optional institutional ID (numeric, e.g., 4446)
        api_url: Optional custom API URL (defaults to subdomain format)
        
    Example config:
        - name: "Public Library"
          driver: "libcal"
          params:
            library_id: "twinsburglibrary"
            iid: 4446
    """

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch events from LibCal."""
        events: list[Event] = []
        documents: list[Document] = []  # LibCal typically doesn't have docs

        library_id = self.params.get("library_id")
        if not library_id:
            raise ValueError("Missing required param: library_id")

        iid = self.params.get("iid")
        
        self.log_info(f"Fetching LibCal events for: {library_id}")

        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Try subdomain-based calendar API first (most common)
            events = await self._try_subdomain_api(client, library_id)
            
            if not events and iid:
                # Try the legacy API with institutional ID
                events = await self._try_legacy_api(client, iid)
            
            if not events:
                # Fall back to RSS feed
                events = await self._try_rss_feed(client, library_id, iid)

        self.log_info(f"Found {len(events)} events")
        return events, documents

    async def _try_subdomain_api(
        self,
        client: httpx.AsyncClient,
        library_id: str,
    ) -> list[Event]:
        """Try the subdomain-based LibCal calendar API."""
        events: list[Event] = []
        
        # LibCal AJAX endpoint for calendar list (returns JSON)
        base_url = f"https://{library_id}.libcal.com"
        
        # Try different API endpoints
        endpoints = [
            f"{base_url}/widget/events?audience=&c=-1&cid=12805",  # Widget endpoint
            f"{base_url}/calendar/events",  # Alternative events endpoint
        ]

        for url in endpoints:
            try:
                await self.rate_limit_delay()
                headers = {
                    "Accept": "application/json, text/javascript, */*",
                    "X-Requested-With": "XMLHttpRequest",
                }
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    continue
                    
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type:
                    continue
                    
                data = response.json()
                
                # Handle different response formats
                if isinstance(data, dict):
                    event_list = data.get("events", data.get("results", []))
                elif isinstance(data, list):
                    event_list = data
                else:
                    continue
                    
                for item in event_list:
                    event = self._parse_event(item)
                    if event:
                        events.append(event)
                        
                if events:
                    self.log_info(f"Found events via subdomain API: {url}")
                    return events
                    
            except Exception as e:
                self.log_warning(f"Subdomain API attempt failed: {e}")
                continue

        return events

    async def _try_legacy_api(
        self,
        client: httpx.AsyncClient,
        iid: int,
    ) -> list[Event]:
        """Try the legacy api3.libcal.com endpoint (returns HTML, not JSON)."""
        events: list[Event] = []
        
        try:
            url = "https://api3.libcal.com/api_events.php"
            await self.rate_limit_delay()
            response = await client.get(
                url,
                params={
                    "iid": iid,
                    "limit": 100,
                    "cal_id": "",
                    "days": 90,  # Look ahead 90 days
                },
            )
            
            if response.status_code != 200:
                return events
            
            # Legacy API returns HTML, not JSON - parse it
            content_type = response.headers.get("content-type", "")
            if "html" in content_type or "text" in content_type:
                events = self._parse_legacy_html(response.text)
                if events:
                    self.log_info(f"Found {len(events)} events via legacy API (HTML)")
                return events
                
            # Try JSON parsing as fallback
            if "json" in content_type:
                data = response.json()
                
                if isinstance(data, dict):
                    event_list = data.get("events", [])
                elif isinstance(data, list):
                    event_list = data
                else:
                    return events
                    
                for item in event_list:
                    event = self._parse_event(item)
                    if event:
                        events.append(event)
                        
                if events:
                    self.log_info("Found events via legacy API (JSON)")
                
        except Exception as e:
            self.log_warning(f"Legacy API failed: {e}")

        return events

    def _parse_legacy_html(self, html: str) -> list[Event]:
        """Parse events from legacy LibCal HTML response."""
        from bs4 import BeautifulSoup
        import re
        
        events: list[Event] = []
        soup = BeautifulSoup(html, "html.parser")
        
        # Each event is in a table with class s-lc-ea-tb
        for table in soup.find_all("table", class_="s-lc-ea-tb"):
            try:
                event = self._parse_legacy_event_table(table)
                if event:
                    events.append(event)
            except Exception as e:
                self.log_warning(f"Error parsing legacy event: {e}")
                continue
                
        return events

    def _parse_legacy_event_table(self, table) -> Optional[Event]:
        """Parse a single event from legacy HTML table format."""
        import re
        
        title = None
        source_url = None
        starts_at = None
        ends_at = None
        location = None
        description = None
        
        # Find title and URL
        title_row = table.find("tr", class_="s-lc-ea-ttit")
        if title_row:
            link = title_row.find("a")
            if link:
                title = link.get_text(strip=True)
                source_url = link.get("href", "")
        
        if not title:
            return None
        
        # Find start time
        from_row = table.find("tr", class_="s-lc-ea-from")
        if from_row:
            td = from_row.find_all("td")
            if len(td) > 1:
                from_text = td[1].get_text(strip=True)
                starts_at = self._parse_legacy_datetime(from_text)
        
        if not starts_at:
            return None
        
        # Find end time
        to_row = table.find("tr", class_="s-lc-ea-to")
        if to_row:
            td = to_row.find_all("td")
            if len(td) > 1:
                to_text = td[1].get_text(strip=True)
                ends_at = self._parse_legacy_datetime(to_text)
        
        # Find location
        loc_row = table.find("tr", class_="s-lc-ea-tloc")
        if loc_row:
            td = loc_row.find_all("td")
            if len(td) > 1:
                location = td[1].get_text(strip=True)
        
        # Find description
        desc_row = table.find("tr", class_="s-lc-ea-tdes")
        if desc_row:
            td = desc_row.find_all("td")
            if len(td) > 1:
                description = td[1].get_text(separator=" ", strip=True)
        
        return Event(
            title=title,
            description=description or "",
            starts_at=starts_at,
            ends_at=ends_at,
            location=location or "",
            source_url=source_url or "",
            event_type=EventType.PROGRAM,
        )

    def _parse_legacy_datetime(self, text: str) -> Optional[datetime]:
        """Parse datetime from legacy format like '2:00pm Sunday, December 14, 2025'."""
        import re
        
        # Pattern: time day, month date, year
        # e.g., "2:00pm Sunday, December 14, 2025"
        patterns = [
            r"(\d{1,2}:\d{2}(?:am|pm)?)\s+\w+,\s+(\w+\s+\d{1,2},\s+\d{4})",
            r"(\d{1,2}:\d{2}\s*(?:am|pm)?)\s+(\w+\s+\d{1,2},\s+\d{4})",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = match.group(1).strip()
                date_str = match.group(2).strip()
                
                # Parse time
                time_formats = ["%I:%M%p", "%I:%M %p", "%H:%M"]
                parsed_time = None
                for fmt in time_formats:
                    try:
                        parsed_time = datetime.strptime(time_str.lower(), fmt)
                        break
                    except ValueError:
                        continue
                
                # Parse date
                date_formats = ["%B %d, %Y", "%b %d, %Y"]
                parsed_date = None
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                
                if parsed_time and parsed_date:
                    return parsed_date.replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute
                    )
                elif parsed_date:
                    return parsed_date
        
        return None

    async def _try_rss_feed(
        self,
        client: httpx.AsyncClient,
        library_id: str,
        iid: Optional[int],
    ) -> list[Event]:
        """Try fetching events from RSS feed."""
        events: list[Event] = []
        
        rss_urls = []
        if iid:
            rss_urls.append(f"https://{library_id}.libcal.com/rss.php?iid={iid}&m=month&cid=-1")
        rss_urls.append(f"https://{library_id}.libcal.com/rss.php")
        
        for url in rss_urls:
            try:
                await self.rate_limit_delay()
                response = await client.get(url)
                
                if response.status_code != 200:
                    continue
                    
                # Parse RSS XML
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.text)
                
                for item in root.findall(".//item"):
                    event = self._parse_rss_item(item)
                    if event:
                        events.append(event)
                        
                if events:
                    self.log_info(f"Found events via RSS feed: {url}")
                    return events
                    
            except Exception as e:
                self.log_warning(f"RSS feed failed: {e}")
                continue

        return events

    def _parse_rss_item(self, item) -> Optional[Event]:
        """Parse an RSS feed item into an Event."""
        try:
            title = item.findtext("title", "").strip()
            if not title:
                return None

            description = item.findtext("description", "")
            link = item.findtext("link", "")
            
            # LibCal RSS includes start/end in namespaced elements
            # Try to find them
            ns = {"libcal": "https://libcal.com/rss_xmlns.php"}
            start_str = item.findtext("libcal:start", namespaces=ns)
            end_str = item.findtext("libcal:end", namespaces=ns)
            
            # Fallback to pubDate
            if not start_str:
                start_str = item.findtext("pubDate", "")
            
            starts_at = self._parse_datetime(start_str) if start_str else None
            if not starts_at:
                return None
                
            ends_at = self._parse_datetime(end_str) if end_str else None
            
            return Event(
                title=title,
                description=description,
                starts_at=starts_at,
                ends_at=ends_at,
                source_url=link,
                event_type=EventType.PROGRAM,
            )
            
        except Exception as e:
            self.log_error(f"Error parsing RSS item: {e}")
            return None

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
