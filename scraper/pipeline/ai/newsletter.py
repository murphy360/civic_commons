"""
AI-powered newsletter generation.

This module generates periodic newsletters summarizing civic events and activities
for a given time window (daily, weekly, monthly, quarterly, annual).

Newsletters are designed to give residents a comprehensive yet digestible overview
of what happened or is happening in their community.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from .client import GeminiClient

logger = logging.getLogger("civic.ai.newsletter")


class PeriodType(str, Enum):
    """Newsletter period types."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


# System prompts for different newsletter types
NEWSLETTER_SYSTEM_PROMPT = """You are creating a community newsletter summarizing civic activities. Write in a friendly, informative tone for residents.

STRUCTURE:
1. **Opening** - One engaging sentence setting the context (e.g., "Here's what happened in [City] this [week/month]...")
2. **Highlights** - 2-3 most important items (major decisions, upcoming deadlines, community events)
3. **Government Meetings** - Brief summary of council/commission meetings with key votes and decisions
4. **Community Events** - Upcoming events worth noting
5. **Looking Ahead** - Any important upcoming dates or deadlines

STYLE GUIDELINES:
- Use bullet points for easy scanning
- Include specific dates, times, amounts where relevant
- Mention ordinance/resolution numbers with plain-language descriptions
- Keep total length appropriate for period:
  * Daily: 200-400 words
  * Weekly: 400-800 words
  * Monthly: 800-1500 words
  * Quarterly: 1500-2500 words
  * Annual: 2500-4000 words

DO NOT:
- Use excessive marketing language ("exciting", "amazing", "don't miss")
- Repeat information already in the subject line
- Include routine procedural items unless significant
- Say "check the website" - provide actual information

FORMAT: Use markdown with headers (##), bullet points, and **bold** for emphasis."""


def get_period_dates(period_type: PeriodType, reference_date: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Calculate start and end dates for a newsletter period.
    
    Args:
        period_type: Type of period (daily, weekly, etc.)
        reference_date: Reference date (defaults to now)
    
    Returns:
        Tuple of (period_start, period_end)
    """
    now = reference_date or datetime.now()
    
    if period_type == PeriodType.DAILY:
        # Yesterday
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    
    elif period_type == PeriodType.WEEKLY:
        # Last full week (Monday to Sunday)
        days_since_monday = now.weekday()
        last_monday = now - timedelta(days=days_since_monday + 7)
        start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=7)) - timedelta(seconds=1)
    
    elif period_type == PeriodType.MONTHLY:
        # Last full month
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_of_this_month - timedelta(seconds=1)
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    elif period_type == PeriodType.QUARTERLY:
        # Last full quarter
        current_quarter = (now.month - 1) // 3
        if current_quarter == 0:
            start_month = 10
            start_year = now.year - 1
        else:
            start_month = (current_quarter - 1) * 3 + 1
            start_year = now.year
        
        start = datetime(start_year, start_month, 1)
        end_month = start_month + 2
        end_year = start_year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        
        # Get last day of end month
        if end_month == 12:
            end = datetime(end_year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = datetime(end_year, end_month + 1, 1) - timedelta(seconds=1)
    
    elif period_type == PeriodType.ANNUAL:
        # Last full year
        start = datetime(now.year - 1, 1, 1)
        end = datetime(now.year, 1, 1) - timedelta(seconds=1)
    
    else:
        raise ValueError(f"Unknown period type: {period_type}")
    
    return start, end


def generate_newsletter_title(period_type: PeriodType, period_start: datetime, city_name: str = "Community") -> str:
    """Generate a title for the newsletter."""
    if period_type == PeriodType.DAILY:
        date_str = period_start.strftime("%B %d, %Y")
        return f"{city_name} Daily Update - {date_str}"
    
    elif period_type == PeriodType.WEEKLY:
        week_end = period_start + timedelta(days=6)
        date_str = f"{period_start.strftime('%b %d')} - {week_end.strftime('%b %d, %Y')}"
        return f"{city_name} Weekly Recap - {date_str}"
    
    elif period_type == PeriodType.MONTHLY:
        date_str = period_start.strftime("%B %Y")
        return f"{city_name} Monthly Newsletter - {date_str}"
    
    elif period_type == PeriodType.QUARTERLY:
        quarter = (period_start.month - 1) // 3 + 1
        return f"{city_name} Quarterly Report - Q{quarter} {period_start.year}"
    
    elif period_type == PeriodType.ANNUAL:
        return f"{city_name} Year in Review - {period_start.year}"
    
    return f"{city_name} Newsletter"


class NewsletterGenerator:
    """
    AI-powered newsletter generation.
    
    Generates periodic newsletters summarizing civic events and activities
    using all available information (events, documents, AI summaries).
    """
    
    def __init__(self, client: GeminiClient):
        """
        Initialize the newsletter generator.
        
        Args:
            client: GeminiClient instance for API calls
        """
        self._client = client
    
    @property
    def enabled(self) -> bool:
        """Check if newsletter generation is enabled."""
        return self._client.enabled
    
    async def generate_newsletter(
        self,
        period_type: PeriodType,
        period_start: datetime,
        period_end: datetime,
        events: List[Dict[str, Any]],
        city_name: str = "Community",
        include_future_events: bool = True,
    ) -> Optional[str]:
        """
        Generate a newsletter for the given period.
        
        Args:
            period_type: Type of period (daily, weekly, etc.)
            period_start: Start of the period
            period_end: End of the period
            events: List of events with their details and AI summaries
            city_name: Name of the city/community
            include_future_events: Whether to include upcoming events section
        
        Returns:
            Generated newsletter markdown or None on error
        """
        if not self._client.enabled:
            logger.warning("Newsletter generation disabled - no API key")
            return None
        
        if not events:
            logger.info(f"No events for newsletter {period_type.value} {period_start}")
            return self._generate_empty_newsletter(period_type, period_start, period_end, city_name)
        
        # Build the context for the AI
        context = self._build_newsletter_context(
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            events=events,
            city_name=city_name,
        )
        
        # Set max tokens based on period type
        max_tokens_map = {
            PeriodType.DAILY: 1024,
            PeriodType.WEEKLY: 2048,
            PeriodType.MONTHLY: 3072,
            PeriodType.QUARTERLY: 4096,
            PeriodType.ANNUAL: 6144,
        }
        max_tokens = max_tokens_map.get(period_type, 2048)
        
        prompt = f"""Generate a {period_type.value} newsletter for {city_name} covering {period_start.strftime('%B %d, %Y')} to {period_end.strftime('%B %d, %Y')}.

Here is the information about events and activities during this period:

{context}

Generate a well-structured newsletter following the guidelines. Use markdown formatting."""
        
        try:
            newsletter = await self._client.generate(
                prompt=prompt,
                system_prompt=NEWSLETTER_SYSTEM_PROMPT,
                temperature=0.3,  # Slightly more creative than summaries
                max_tokens=max_tokens,
            )
            
            if newsletter:
                logger.info(f"Generated {period_type.value} newsletter ({len(newsletter)} chars)")
            
            return newsletter
            
        except Exception as e:
            logger.error(f"Error generating newsletter: {e}")
            return None
    
    def _build_newsletter_context(
        self,
        period_type: PeriodType,
        period_start: datetime,
        period_end: datetime,
        events: List[Dict[str, Any]],
        city_name: str,
    ) -> str:
        """Build context string for newsletter generation."""
        sections = []
        
        # Group events by category
        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for event in events:
            category = event.get("category", "Other") or "Other"
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(event)
        
        # Government meetings first
        meeting_categories = ["City Council", "Council", "Commission", "Board", "Committee"]
        for category, cat_events in sorted(by_category.items()):
            is_meeting = any(mc.lower() in category.lower() for mc in meeting_categories)
            
            if is_meeting:
                sections.append(f"\n## {category}\n")
                for event in sorted(cat_events, key=lambda e: e.get("start_time", datetime.min)):
                    event_date = event.get("start_time")
                    date_str = event_date.strftime("%B %d") if event_date else "Date unknown"
                    
                    sections.append(f"\n### {event.get('title', 'Meeting')} - {date_str}\n")
                    
                    if event.get("ai_summary"):
                        sections.append(event["ai_summary"])
                    else:
                        sections.append(event.get("description", "No details available."))
                    
                    # Include document references
                    docs = event.get("documents", [])
                    if docs:
                        sections.append("\nRelated documents:")
                        for doc in docs[:5]:  # Limit to 5 docs per event
                            sections.append(f"- {doc.get('title', 'Document')}")
        
        # Community events
        community_events = []
        for category, cat_events in by_category.items():
            is_meeting = any(mc.lower() in category.lower() for mc in meeting_categories)
            if not is_meeting:
                community_events.extend(cat_events)
        
        if community_events:
            sections.append("\n## Community Events\n")
            for event in sorted(community_events, key=lambda e: e.get("start_time", datetime.min)):
                event_date = event.get("start_time")
                date_str = event_date.strftime("%B %d") if event_date else "Date TBD"
                
                title = event.get("title", "Event")
                location = event.get("location", "")
                description = event.get("description", "")
                
                sections.append(f"- **{title}** ({date_str})")
                if location:
                    sections.append(f"  Location: {location}")
                if description and len(description) < 200:
                    sections.append(f"  {description}")
        
        return "\n".join(sections)
    
    def _generate_empty_newsletter(
        self,
        period_type: PeriodType,
        period_start: datetime,
        period_end: datetime,
        city_name: str,
    ) -> str:
        """Generate a placeholder newsletter when no events exist."""
        period_desc = {
            PeriodType.DAILY: "day",
            PeriodType.WEEKLY: "week",
            PeriodType.MONTHLY: "month",
            PeriodType.QUARTERLY: "quarter",
            PeriodType.ANNUAL: "year",
        }
        
        return f"""## {city_name} {period_type.value.title()} Update

**{period_start.strftime('%B %d, %Y')} - {period_end.strftime('%B %d, %Y')}**

No significant civic events were recorded during this {period_desc.get(period_type, 'period')}.

Check back for the next update, or visit the Events page to see upcoming activities in the community.
"""
