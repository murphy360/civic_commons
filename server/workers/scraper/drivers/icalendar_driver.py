"""
Purpose: Driver for iCalendar (.ics) feeds - structured calendar data
Dependencies: httpx for HTTP, icalendar for parsing
Consumed by: Worker for city calendars, meeting schedules
Side effects: HTTP requests to iCalendar feed
"""

from datetime import datetime, date, timezone
from typing import Optional
import re

import httpx
from icalendar import Calendar
from zoneinfo import ZoneInfo

from .base import BaseDriver
from models import Event, Document, EventType

# Default timezone fallback (should come from config)
DEFAULT_TIMEZONE = "America/New_York"


class ICalendarDriver(BaseDriver):
    """
    Driver for iCalendar (.ics) feeds.
    
    iCalendar feeds are structured calendar data that many CivicPlus and
    municipal websites provide. These are more reliable than HTML scraping.
    
    Expected params in YAML config:
        feed_url: URL of the iCalendar feed
        event_types: Optional list of keywords to filter events (e.g., ["council", "meeting"])
        
    Example config:
        - name: "City Calendar"
          driver: "icalendar"
          params:
            feed_url: "https://www.mytwinsburg.com/common/modules/iCalendar/iCalendar.aspx?catID=14&feed=calendar"
            event_types: ["meeting", "council", "committee", "commission", "board"]
    """

    # Keywords that indicate government/civic meetings vs community events
    CIVIC_KEYWORDS = [
        "council", "committee", "commission", "board", "meeting",
        "hearing", "session", "caucus", "zoning", "planning",
        "arb", "bza", "jedi", "civil service", "environmental",
        "public works", "finance", "safety", "parks"
    ]

    def _get_local_timezone(self) -> ZoneInfo:
        """Get the local timezone from config, with fallback."""
        tz_name = self.params.get("timezone", DEFAULT_TIMEZONE)
        return ZoneInfo(tz_name)

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch events from iCalendar feed."""
        events: list[Event] = []
        documents: list[Document] = []

        feed_url = self.params.get("feed_url")
        if not feed_url:
            raise ValueError("Missing required param: feed_url")

        self.log_info(f"Fetching iCalendar feed: {feed_url}")

        # Get filter keywords from config, or use defaults for civic events
        event_filter = self.params.get("event_types", [])
        filter_civic_only = self.params.get("civic_only", True)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "CivicCommons/1.0 (civic data aggregator)",
                "Accept": "text/calendar, application/ics, */*",
            }
        ) as client:
            await self.rate_limit_delay()
            response = await client.get(feed_url)
            response.raise_for_status()

            # Parse the iCalendar data
            cal = Calendar.from_ical(response.content)

            # Process VEVENT components
            for component in cal.walk():
                if component.name == "VEVENT":
                    event = self._parse_vevent(component, event_filter, filter_civic_only)
                    if event:
                        events.append(event)

        self.log_info(f"Found {len(events)} events from iCalendar feed")
        return events, documents

    def _parse_vevent(
        self, 
        vevent, 
        event_filter: list[str],
        filter_civic_only: bool
    ) -> Optional[Event]:
        """Parse a VEVENT component into an Event."""
        try:
            # Get summary (title)
            summary = str(vevent.get("SUMMARY", "")).strip()
            if not summary:
                return None

            # Skip cancelled events
            if summary.lower().startswith("cancelled"):
                self.log_debug(f"Skipping cancelled event: {summary}")
                return None

            # Apply filters
            summary_lower = summary.lower()
            
            # If specific event types requested, filter by those
            if event_filter:
                if not any(kw.lower() in summary_lower for kw in event_filter):
                    return None
            # Otherwise, if civic_only is True, filter to civic events
            elif filter_civic_only:
                if not any(kw in summary_lower for kw in self.CIVIC_KEYWORDS):
                    self.log_debug(f"Skipping non-civic event: {summary}")
                    return None

            # Get start time
            dtstart = vevent.get("DTSTART")
            if not dtstart:
                return None
            
            starts_at = self._parse_datetime(dtstart)
            if not starts_at:
                return None

            # Get end time
            dtend = vevent.get("DTEND")
            ends_at = self._parse_datetime(dtend) if dtend else None

            # Get location
            location = self._clean_location(str(vevent.get("LOCATION", "")))

            # Get description and source URL
            description = str(vevent.get("DESCRIPTION", "")).strip()
            
            # Extract source URL from description if present
            source_url = None
            url_match = re.search(r'https?://[^\s<>"]+', description)
            if url_match:
                source_url = url_match.group(0)
            
            # Clean description (remove URL from text)
            if source_url:
                description = description.replace(source_url, "").strip()

            # Get UID for deduplication
            uid = str(vevent.get("UID", ""))

            # Infer event type
            event_type = self._infer_event_type(summary)

            # Clean up title
            title = self._clean_title(summary)

            return Event(
                title=title,
                description=description if description else None,
                starts_at=starts_at,
                ends_at=ends_at,
                event_type=event_type,
                location=location if location else None,
                source_url=source_url,
            )

        except Exception as e:
            self.log_error(f"Error parsing VEVENT: {e}")
            return None

    def _parse_datetime(self, dt_prop) -> Optional[datetime]:
        """
        Parse an iCalendar datetime property and convert to local timezone.
        
        iCal datetimes can be:
        1. UTC (DTSTART:20251217T180000Z)
        2. Timezone-aware (DTSTART;TZID=America/New_York:20251217T180000)
        3. Floating/naive (DTSTART:20251217T180000) - assumed local
        4. Date-only (DTSTART;VALUE=DATE:20251217) - all-day events
        """
        try:
            dt = dt_prop.dt
            
            # Handle date-only values (all-day events)
            if isinstance(dt, date) and not isinstance(dt, datetime):
                return datetime.combine(dt, datetime.min.time())
            
            # Handle datetime
            if isinstance(dt, datetime):
                if dt.tzinfo:
                    # Convert timezone-aware datetime to local timezone, then make naive
                    local_tz = self._get_local_timezone()
                    local_dt = dt.astimezone(local_tz)
                    return local_dt.replace(tzinfo=None)
                else:
                    # Naive datetime - assume it's already in local time
                    return dt
            
            return None
        except Exception:
            return None

    def _clean_location(self, location: str) -> str:
        """Clean up location text from iCal format."""
        if not location:
            return ""
        
        # Remove HTML tags
        location = re.sub(r'<[^>]+>', '', location)
        
        # Clean up HTML entities
        location = location.replace("&nbsp;", " ")
        location = location.replace("\\,", ",")
        location = location.replace("\\n", ", ")
        
        # Clean up whitespace
        location = " ".join(location.split())
        
        return location.strip()

    def _clean_title(self, title: str) -> str:
        """Clean up event title."""
        # Remove "Cancelled - " prefix if somehow it got through
        title = re.sub(r'^Cancelled\s*-?\s*', '', title, flags=re.IGNORECASE)
        
        # Standardize common abbreviations
        replacements = {
            "ARB Meeting": "Architectural Review Board Meeting",
            "BZA Meeting": "Board of Zoning Appeals Meeting",
            "JEDI Meeting": "JEDI Committee Meeting",
            "JEDI Committee": "JEDI Committee Meeting",
        }
        
        for short, full in replacements.items():
            if title == short:
                return full
        
        return title.strip()

    def _infer_event_type(self, title: str) -> EventType:
        """Infer event type from title."""
        title_lower = title.lower()
        
        # Public hearings
        if "hearing" in title_lower:
            return EventType.HEARING
        
        # Work sessions / workshops
        elif "work session" in title_lower or "workshop" in title_lower:
            return EventType.WORKSHOP
        
        # Programs / classes (recreation, library, etc.)
        elif any(kw in title_lower for kw in [
            "yoga", "class", "training", "course", "lesson",
            "dance", "dancing", "tournament", "swim", "fitness"
        ]):
            return EventType.PROGRAM
        
        # Community events (festivals, celebrations, etc.)
        elif any(kw in title_lower for kw in [
            "celebration", "festival", "parade", "ceremony",
            "gingerbread", "holiday", "hanukkah", "christmas"
        ]):
            return EventType.COMMUNITY
        
        # Deadlines
        elif "deadline" in title_lower:
            return EventType.DEADLINE
        
        # Default to meeting for council, committee, board, etc.
        else:
            return EventType.MEETING

