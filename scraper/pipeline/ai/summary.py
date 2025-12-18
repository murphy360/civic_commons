"""
Cascading AI-powered summary generation.

This module implements a hierarchical summary system where changes cascade upward:
- Document added → Event Summary regenerated
- Event Summary updated → Daily Summary regenerated
- Daily Summary updated → Weekly Summary regenerated
- Weekly → Monthly → Quarterly → Annual

Each level summarizes its children, creating increasingly condensed overviews.
"""

import logging
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from dataclasses import dataclass, field

from .client import GeminiClient, MODELS

logger = logging.getLogger("civic.ai.summary")


@dataclass
class GeneratedSummary:
    """Result from summary generation, including the model used."""
    text: str
    model: str  # Model key (e.g., 'flash', 'flash-2.5', 'pro')
    
    @property
    def model_name(self) -> str:
        """Get the full model name from the URL."""
        url = MODELS.get(self.model, "")
        # Extract model name from URL like ".../gemini-2.0-flash:generateContent"
        if "/models/" in url:
            return url.split("/models/")[1].split(":")[0]
        return self.model
    
    @property
    def text_with_footer(self) -> str:
        """Get the summary text with a generation footer."""
        today = datetime.now().strftime("%B %d, %Y")
        footer = f"\n\n---\n*Generated: {today} by {self.model_name}*"
        return self.text + footer


class SummaryType(str, Enum):
    """Summary hierarchy types (from most granular to most aggregated)."""
    EVENT = "event"         # Summary of a single event and its documents
    DAILY = "daily"         # Summary of all events on a single day
    WEEKLY = "weekly"       # Summary of a week's daily summaries
    MONTHLY = "monthly"     # Summary of a month's weekly summaries
    QUARTERLY = "quarterly" # Summary of a quarter's monthly summaries
    ANNUAL = "annual"       # Summary of a year's quarterly summaries


# Hierarchy mapping: child → parent
SUMMARY_HIERARCHY = {
    SummaryType.EVENT: SummaryType.DAILY,
    SummaryType.DAILY: SummaryType.WEEKLY,
    SummaryType.WEEKLY: SummaryType.MONTHLY,
    SummaryType.MONTHLY: SummaryType.QUARTERLY,
    SummaryType.QUARTERLY: SummaryType.ANNUAL,
    SummaryType.ANNUAL: None,
}


@dataclass
class SummaryContext:
    """Context for generating a summary."""
    summary_type: SummaryType
    city_id: str
    city_name: str
    period_start: datetime
    period_end: datetime
    event_id: Optional[int] = None
    
    # For event summaries
    event_title: Optional[str] = None
    documents: List[Dict[str, Any]] = field(default_factory=list)
    
    # For period summaries (daily, weekly, etc.)
    child_summaries: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


# System prompts for different summary types
SUMMARY_PROMPTS = {
    SummaryType.EVENT: """You are summarizing a civic event (meeting, hearing, etc.) based on its documents.

Your summary should capture:
1. **Purpose** - What was this meeting/event about?
2. **Key Decisions** - Any votes, approvals, or official actions taken
3. **Discussion Points** - Major topics discussed, concerns raised
4. **Action Items** - What happens next? Follow-ups mentioned?
5. **Public Input** - Any notable public comments or participation

FORMAT:
- Use markdown with headers and bullet points
- Be specific: include vote counts, dollar amounts, names of key items
- Length: 150-400 words depending on complexity
- If documents are incomplete (e.g., no minutes yet), note what's available

IMPORTANT:
- Start directly with the content - NO preamble like "Here is the summary" or "Of course"
- Write in past tense as a historical record
- Avoid relative time references like "today", "this week", "recently" - use specific dates
- This is an archival document that may be read years later

TONE: Professional, informative, neutral. Let residents understand what happened without editorializing.""",

    SummaryType.DAILY: """You are creating a daily summary of civic activities for a community.

Summarize what happened on this specific date based on the event summaries provided. Focus on:
1. **Highlights** - Most significant event or decision of the day
2. **Meeting Summaries** - Brief recap of each meeting that occurred
3. **Community Events** - Non-government activities worth noting

FORMAT:
- 200-400 words
- Use bullet points for scanning
- Lead with the most important item

IMPORTANT:
- Start directly with the content - NO preamble like "Here is the summary" or "Of course"
- Write as a historical record, not a live update
- Avoid phrases like "today", "this morning" - use specific dates or just describe what happened
- Do NOT include "tomorrow's preview" or forward-looking statements about upcoming events
- This summary may be read months or years after the events occurred

TONE: Clear and informative, like a news archive entry.""",

    SummaryType.WEEKLY: """You are creating a weekly summary of civic activities.

Synthesize the daily summaries into a cohesive week overview:
1. **Week Overview** - One paragraph capturing the week's major developments
2. **Key Decisions** - Most important votes, approvals, changes
3. **Notable Discussions** - Significant debates or community concerns raised
4. **By the Numbers** - Any interesting stats (attendance, votes, amounts)

FORMAT:
- 400-800 words
- Start with the big picture, then details
- Group related items together
- Reference specific dates (e.g., "On December 9th..." not "On Monday...")

IMPORTANT:
- Start directly with the content - NO preamble like "Here is the summary" or "Of course"
- Write as a historical record in past tense
- Avoid relative time language like "this past week", "recently", "upcoming"
- Do NOT include "what to watch next week" or future-looking content
- Avoid dramatic framing like "a week defined by..." - just report what happened
- This is an archival document that may be read years later

TONE: Informative and factual, suitable for historical reference.""",

    SummaryType.MONTHLY: """You are creating a monthly summary of civic activities.

Create a comprehensive but digestible month overview:
1. **Month Overview** - 2-3 sentences capturing the month's key activities
2. **Major Developments** - Significant decisions, projects, changes
3. **Ongoing Initiatives** - Progress updates on multi-month projects
4. **Community Engagement** - Trends in public participation, concerns raised

FORMAT:
- 800-1500 words
- Use clear section headers
- Include specific dates for context

IMPORTANT:
- Start directly with the content - NO preamble like "Here is the summary" or "Of course"
- Write as a historical record in past tense
- Avoid relative time like "this month", "recently", "looking ahead"
- Do NOT include forward-looking content about next month
- Use specific dates and concrete facts
- This is an archival document that may be read years later

TONE: Professional newsletter style, comprehensive but scannable.""",

    SummaryType.QUARTERLY: """You are creating a quarterly summary of civic activities.

Synthesize three months into a strategic overview:
1. **Quarter Overview** - Major themes and accomplishments
2. **Key Milestones** - Significant decisions, project completions
3. **Policy Changes** - New ordinances, policy shifts
4. **Budget & Finance** - Financial highlights, major expenditures
5. **Community Engagement** - Participation trends, notable initiatives

FORMAT:
- 1500-2500 words
- Include year-over-year comparisons where relevant
- Suitable for sharing with stakeholders

IMPORTANT:
- Start directly with the content - NO preamble like "Here is the summary" or "Of course"
- Write as a historical record in past tense
- Avoid relative time references - use specific dates and quarters (e.g., "Q3 2025")
- Do NOT include forward-looking content about next quarter
- This is an archival document that may be read years later

TONE: Executive summary style, authoritative but accessible.""",

    SummaryType.ANNUAL: """You are creating an annual summary of civic activities.

Create a comprehensive year-in-review:
1. **Year in Headlines** - 5-7 most significant events/decisions
2. **Governance** - Leadership changes, organizational updates
3. **Major Projects** - Status of significant initiatives
4. **Budget Review** - Key financial decisions, outcomes
5. **Community Milestones** - Notable achievements, events
6. **Challenges Addressed** - How issues were handled

FORMAT:
- 2500-4000 words
- Organized chronologically or thematically
- Include highlights from each quarter

IMPORTANT:
- Start directly with the content - NO preamble like "Here is the summary" or "Of course"
- Write as a historical record in past tense
- Avoid forward-looking statements about the next year
- Use specific dates and concrete facts throughout
- This is an archival document that will be referenced for years

TONE: Reflective, comprehensive, suitable for annual report or historical archive."""
}


# Token limits by summary type
MAX_TOKENS = {
    SummaryType.EVENT: 1024,
    SummaryType.DAILY: 1024,
    SummaryType.WEEKLY: 4096,      # Increased for thinking model
    SummaryType.MONTHLY: 6144,     # Increased for thinking model
    SummaryType.QUARTERLY: 8192,   # Increased for thinking model
    SummaryType.ANNUAL: 8192,      # Increased for thinking model
}

# Summary types that should use the thinking model for deeper analysis
USE_PRO_MODEL = {
    SummaryType.WEEKLY,
    SummaryType.MONTHLY,
    SummaryType.QUARTERLY,
}

# Annual summaries use Gemini 3 Pro Preview for most comprehensive analysis
USE_PRO_3_MODEL = {
    SummaryType.ANNUAL,
}


def get_period_bounds(
    summary_type: SummaryType,
    reference_date: Optional[datetime] = None
) -> Tuple[datetime, datetime]:
    """
    Calculate the period bounds for a given summary type.
    
    For generating "current" period summaries (e.g., today's daily, this week's weekly).
    """
    now = reference_date or datetime.now()
    
    if summary_type == SummaryType.EVENT:
        # Events don't have period bounds in this sense
        raise ValueError("EVENT summaries use event start/end times, not period bounds")
    
    elif summary_type == SummaryType.DAILY:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(microseconds=1)
    
    elif summary_type == SummaryType.WEEKLY:
        # Week starts Monday
        days_since_monday = now.weekday()
        start = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=7) - timedelta(microseconds=1)
    
    elif summary_type == SummaryType.MONTHLY:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Last day of month
        if now.month == 12:
            end = now.replace(year=now.year + 1, month=1, day=1) - timedelta(microseconds=1)
        else:
            end = now.replace(month=now.month + 1, day=1) - timedelta(microseconds=1)
    
    elif summary_type == SummaryType.QUARTERLY:
        quarter = (now.month - 1) // 3
        start_month = quarter * 3 + 1
        start = now.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        # End of quarter
        end_month = start_month + 3
        if end_month > 12:
            end = now.replace(year=now.year + 1, month=1, day=1) - timedelta(microseconds=1)
        else:
            end = now.replace(month=end_month, day=1) - timedelta(microseconds=1)
    
    elif summary_type == SummaryType.ANNUAL:
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(year=now.year + 1, month=1, day=1) - timedelta(microseconds=1)
    
    else:
        raise ValueError(f"Unknown summary type: {summary_type}")
    
    return start, end


def get_parent_period_bounds(
    child_type: SummaryType,
    child_period_start: datetime
) -> Optional[Tuple[SummaryType, datetime, datetime]]:
    """
    Get the parent period that contains the given child period.
    
    Returns (parent_type, parent_start, parent_end) or None if no parent.
    """
    parent_type = SUMMARY_HIERARCHY.get(child_type)
    if parent_type is None:
        return None
    
    # Get the parent period that contains this child period
    return (parent_type, *get_period_bounds(parent_type, child_period_start))


def get_child_period_bounds(
    parent_type: SummaryType,
    parent_start: datetime,
    parent_end: datetime
) -> List[Tuple[datetime, datetime]]:
    """
    Get all child periods within a parent period.
    
    E.g., for a weekly summary, get all 7 daily periods.
    """
    child_type = None
    for ct, pt in SUMMARY_HIERARCHY.items():
        if pt == parent_type:
            child_type = ct
            break
    
    if child_type is None or child_type == SummaryType.EVENT:
        return []
    
    periods = []
    current = parent_start
    
    while current < parent_end:
        child_start, child_end = get_period_bounds(child_type, current)
        # Only include if it falls within parent period
        if child_start >= parent_start and child_end <= parent_end:
            periods.append((child_start, child_end))
        # Move to next period
        if child_type == SummaryType.DAILY:
            current += timedelta(days=1)
        elif child_type == SummaryType.WEEKLY:
            current += timedelta(weeks=1)
        elif child_type == SummaryType.MONTHLY:
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        elif child_type == SummaryType.QUARTERLY:
            if current.month >= 10:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 3)
    
    return periods


class SummaryGenerator:
    """
    AI-powered cascading summary generation.
    
    Generates summaries at multiple levels (event, daily, weekly, etc.)
    and handles cascade updates when lower-level summaries change.
    """
    
    def __init__(self, client: GeminiClient):
        """Initialize with a GeminiClient instance."""
        self._client = client
    
    @property
    def enabled(self) -> bool:
        """Check if summary generation is enabled."""
        return self._client.enabled
    
    async def generate_event_summary(
        self,
        event_title: str,
        event_date: datetime,
        documents: List[Dict[str, Any]],
        city_name: str,
        existing_summary: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate or update a summary for a single event.
        
        Args:
            event_title: Title of the event
            event_date: When the event occurred
            documents: List of documents with {title, content, doc_type, ai_summary}
            city_name: Name of the city
            existing_summary: Previous summary if this is an update
        
        Returns:
            Generated summary markdown or None on error
        """
        if not self._client.enabled:
            logger.warning("Summary generation disabled - no API key")
            return None
        
        if not documents:
            logger.info(f"No documents for event summary: {event_title}")
            return None
        
        # Build document context
        doc_context = []
        for doc in documents:
            doc_type = doc.get('doc_type', 'document')
            title = doc.get('title', 'Untitled')
            
            # Use AI summary if available, otherwise truncate content
            content = doc.get('ai_summary') or doc.get('content', '')
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            
            doc_context.append(f"### {doc_type.title()}: {title}\n{content}")
        
        context = "\n\n".join(doc_context)
        
        update_note = ""
        if existing_summary:
            update_note = f"\n\nPrevious summary (for context - update rather than replace if new info adds to it):\n{existing_summary}"
        
        prompt = f"""Summarize this civic event:

**Event:** {event_title}
**Date:** {event_date.strftime('%B %d, %Y')}
**City:** {city_name}

**Available Documents:**
{context}
{update_note}

Generate a comprehensive summary based on the available documents."""

        try:
            # Use flash model for event summaries
            model = "flash"
            summary = await self._client.generate(
                prompt=prompt,
                system_prompt=SUMMARY_PROMPTS[SummaryType.EVENT],
                temperature=0.3,
                max_tokens=MAX_TOKENS[SummaryType.EVENT],
                model=model,
            )
            
            if summary:
                logger.info(f"Generated event summary for '{event_title}' ({len(summary)} chars) using {model}")
                return GeneratedSummary(text=summary, model=model)
            
            return None
            
        except Exception as e:
            logger.error(f"Error generating event summary: {e}")
            return None
    
    async def generate_period_summary(
        self,
        summary_type: SummaryType,
        period_start: datetime,
        period_end: datetime,
        city_name: str,
        child_summaries: List[Dict[str, Any]],
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[GeneratedSummary]:
        """
        Generate a period summary (daily, weekly, monthly, etc.).
        
        Args:
            summary_type: Type of summary to generate
            period_start: Start of the period
            period_end: End of the period
            city_name: Name of the city
            child_summaries: Summaries from child level (e.g., event summaries for daily)
            events: Optional list of events (used if no child summaries exist yet)
        
        Returns:
            Generated summary markdown or None on error
        """
        if not self._client.enabled:
            logger.warning("Summary generation disabled - no API key")
            return None
        
        if summary_type == SummaryType.EVENT:
            raise ValueError("Use generate_event_summary for event summaries")
        
        # Build context from child summaries
        if child_summaries:
            context = self._build_child_context(summary_type, child_summaries)
        elif events:
            # Fallback: build from events directly
            context = self._build_event_context(events)
        else:
            logger.info(f"No content for {summary_type.value} summary {period_start}")
            return self._generate_empty_summary(summary_type, period_start, period_end, city_name)
        
        period_desc = self._format_period(summary_type, period_start, period_end)
        
        prompt = f"""Generate a {summary_type.value} summary for {city_name}.

**Period:** {period_desc}

**Content to summarize:**
{context}

Create a cohesive {summary_type.value} summary following the guidelines."""

        try:
            # Use pro-3 model for annual summaries (Gemini 3 Pro Preview - most comprehensive)
            if summary_type in USE_PRO_3_MODEL:
                model = "pro-3"
                logger.info(f"Using {model} model (Gemini 3 Pro Preview) for {summary_type.value} summary")
            # Use pro model for weekly/monthly/quarterly summaries (deeper analysis)
            elif summary_type in USE_PRO_MODEL:
                model = "pro"
                logger.info(f"Using {model} model for {summary_type.value} summary")
            else:
                model = "flash"
                
            summary = await self._client.generate(
                prompt=prompt,
                system_prompt=SUMMARY_PROMPTS[summary_type],
                temperature=0.3,
                max_tokens=MAX_TOKENS[summary_type],
                model=model,
            )
            
            if summary:
                logger.info(f"Generated {summary_type.value} summary ({len(summary)} chars) using {model}")
                return GeneratedSummary(text=summary, model=model)
            
            return None
            
        except Exception as e:
            logger.error(f"Error generating {summary_type.value} summary: {e}")
            return None
    
    def _build_child_context(
        self,
        parent_type: SummaryType,
        child_summaries: List[Dict[str, Any]]
    ) -> str:
        """Build context string from child summaries."""
        sections = []
        
        for child in sorted(child_summaries, key=lambda x: x.get('period_start', datetime.min)):
            title = child.get('title', 'Summary')
            summary_text = child.get('summary_text', '')
            period_start = child.get('period_start')
            
            if period_start:
                date_str = period_start.strftime('%B %d, %Y')
                sections.append(f"## {title} ({date_str})\n{summary_text}")
            else:
                sections.append(f"## {title}\n{summary_text}")
        
        return "\n\n---\n\n".join(sections)
    
    def _build_event_context(self, events: List[Dict[str, Any]]) -> str:
        """Build context string from events (fallback when no summaries exist)."""
        sections = []
        
        for event in sorted(events, key=lambda x: x.get('start_time', datetime.min)):
            title = event.get('title', 'Event')
            start_time = event.get('start_time')
            ai_summary = event.get('ai_summary', '')
            description = event.get('description', '')
            
            date_str = start_time.strftime('%B %d') if start_time else 'Date TBD'
            content = ai_summary or description or 'No details available.'
            
            sections.append(f"### {title} ({date_str})\n{content}")
        
        return "\n\n".join(sections)
    
    def _format_period(
        self,
        summary_type: SummaryType,
        period_start: datetime,
        period_end: datetime
    ) -> str:
        """Format period description for prompts."""
        if summary_type == SummaryType.DAILY:
            return period_start.strftime('%A, %B %d, %Y')
        elif summary_type == SummaryType.WEEKLY:
            return f"Week of {period_start.strftime('%B %d')} - {period_end.strftime('%B %d, %Y')}"
        elif summary_type == SummaryType.MONTHLY:
            return period_start.strftime('%B %Y')
        elif summary_type == SummaryType.QUARTERLY:
            quarter = (period_start.month - 1) // 3 + 1
            return f"Q{quarter} {period_start.year}"
        elif summary_type == SummaryType.ANNUAL:
            return str(period_start.year)
        else:
            return f"{period_start.strftime('%B %d')} - {period_end.strftime('%B %d, %Y')}"
    
    def _generate_empty_summary(
        self,
        summary_type: SummaryType,
        period_start: datetime,
        period_end: datetime,
        city_name: str,
    ) -> GeneratedSummary:
        """Generate a placeholder summary when no content exists."""
        period_desc = self._format_period(summary_type, period_start, period_end)
        
        text = f"""## {city_name} {summary_type.value.title()} Summary

**{period_desc}**

No significant civic activities were recorded during this period.

Check back for the next update, or visit the Events page to see upcoming activities in the community.
"""
        # Empty summaries aren't generated by AI, but we mark them as such
        return GeneratedSummary(text=text, model="none")


# Convenience function for backwards compatibility
def generate_summary_title(summary_type: SummaryType, period_end: datetime, city_name: str = "") -> str:
    """Generate a title for a summary."""
    if summary_type == SummaryType.DAILY:
        return f"{city_name} Daily Update - {period_end.strftime('%B %d, %Y')}".strip()
    elif summary_type == SummaryType.WEEKLY:
        return f"{city_name} Week in Review - {period_end.strftime('%B %d, %Y')}".strip()
    elif summary_type == SummaryType.MONTHLY:
        return f"{city_name} Monthly Summary - {period_end.strftime('%B %Y')}".strip()
    elif summary_type == SummaryType.QUARTERLY:
        quarter = (period_end.month - 1) // 3 + 1
        return f"{city_name} Q{quarter} {period_end.year} Summary".strip()
    elif summary_type == SummaryType.ANNUAL:
        return f"{city_name} {period_end.year} Year in Review".strip()
    else:
        return f"{city_name} Summary - {period_end.strftime('%B %d, %Y')}".strip()
