"""
AI-powered event processing using Gemini or other LLMs.

This module provides intelligent processing of scraped events:
- Normalizes event titles and descriptions
- Extracts structured data (time, location, participants)
- Validates event data quality
- Detects and merges duplicate events
- Categorizes events by type

Can be used standalone or via MCP tools.

Note: Specialized functionality has been moved to submodules:
- pipeline.ai.client.GeminiClient - API client
- pipeline.ai.pdf_extractor.extract_pdf_text - PDF extraction
- pipeline.ai.linker.DocumentLinker - Document-to-event linking
- pipeline.ai.summarizer.EventSummarizer - Event summary generation
"""

import json
import logging
from typing import Optional

from models import Event, EventType
from .ai import GeminiClient, extract_pdf_text, DocumentLinker, EventSummarizer

logger = logging.getLogger("civic.ai")


class AIEventProcessor:
    """
    Process and enrich events using AI.
    
    This class acts as a facade, delegating specialized operations
    to dedicated modules while maintaining backward compatibility.
    """
    
    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini"):
        """
        Initialize the AI processor.
        
        Args:
            api_key: API key for the AI provider. If None, reads from environment.
            provider: AI provider to use ("gemini", "openai", "anthropic")
        """
        self.provider = provider
        self._gemini = GeminiClient(api_key)
        
        # Initialize specialized processors
        self._linker = DocumentLinker(self._gemini)
        self._summarizer = EventSummarizer(self._gemini)
    
    @property
    def enabled(self) -> bool:
        """Check if AI processing is enabled."""
        return self._gemini.enabled
    
    @property
    def api_key(self) -> Optional[str]:
        """Get the API key (for backward compatibility)."""
        return self._gemini.api_key
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self._gemini.close()
    
    async def _call_gemini(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        Call Gemini API with a prompt.
        
        Delegates to GeminiClient.generate().
        
        Returns:
            Generated text response or None on error
        """
        return await self._gemini.generate(prompt, system_prompt)
    
    async def normalize_event(self, event: Event, source_context: str = "") -> Event:
        """
        Normalize and clean up an event using AI.
        
        - Cleans up title formatting
        - Standardizes date/time representation
        - Extracts location details
        - Improves description quality
        
        Args:
            event: The event to normalize
            source_context: Additional context about the source
            
        Returns:
            Normalized event (or original if AI unavailable)
        """
        if not self.enabled:
            return event
        
        system_prompt = """You are a data normalization assistant for civic event data.
Your job is to clean up and standardize event information from government websites.

Rules:
- Keep titles concise but descriptive
- Remove redundant information
- For locations: Only include city/state if you KNOW the actual city from the source context. Do NOT add placeholder text like "Anytown" or "[City]"
- If the location is just "Council Chambers" or similar, leave it as-is without adding unknown city/state
- Keep descriptions factual and clear
- Preserve all important details like times, addresses, and contact info

Always respond with valid JSON only, no markdown formatting."""

        prompt = f"""Normalize this civic event data:

Title: {event.title}
Description: {event.description or 'None'}
Location: {event.location or 'Unknown'}
Start Time: {event.starts_at.isoformat() if event.starts_at else 'Unknown'}
Source: {source_context}

Return a JSON object with these fields:
- title: cleaned up title
- description: improved description (or null if none needed)
- location: standardized location string (or null)
- event_type: one of [meeting, hearing, workshop, community, program, deadline]

JSON response:"""

        response = await self._call_gemini(prompt, system_prompt)
        
        if not response:
            return event
        
        try:
            # Parse JSON response
            data = json.loads(response.strip().removeprefix("```json").removesuffix("```"))
            
            # Update event with normalized data
            if data.get("title"):
                event.title = data["title"]
            if data.get("description"):
                event.description = data["description"]
            if data.get("location"):
                event.location = data["location"]
            if data.get("event_type"):
                try:
                    event.event_type = EventType(data["event_type"])
                except ValueError:
                    pass
            
            return event
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse AI response: {e}")
            return event
    
    async def detect_duplicates(
        self, 
        new_event: Event, 
        existing_events: list[Event]
    ) -> Optional[Event]:
        """
        Detect if a new event is a duplicate of an existing one.
        
        Uses AI to understand semantic similarity beyond exact matching.
        
        Args:
            new_event: The newly scraped event
            existing_events: List of existing events to check against
            
        Returns:
            The matching existing event if duplicate found, None otherwise
        """
        if not self.enabled or not existing_events:
            return None
        
        # Pre-filter by date range (within 3 days)
        candidates = []
        for existing in existing_events:
            if existing.starts_at and new_event.starts_at:
                delta = abs((existing.starts_at - new_event.starts_at).days)
                if delta <= 3:
                    candidates.append(existing)
        
        if not candidates:
            return None
        
        # Build comparison prompt
        existing_list = "\n".join([
            f"{i+1}. Title: {e.title}, Date: {e.starts_at.isoformat() if e.starts_at else 'Unknown'}, Location: {e.location or 'Unknown'}"
            for i, e in enumerate(candidates[:10])  # Limit to 10 candidates
        ])
        
        system_prompt = """You are a duplicate detection assistant for civic event data.
Your job is to identify if a new event is the same as an existing one, even if the wording differs.

Consider events as duplicates if they:
- Refer to the same meeting/event (even with different titles)
- Have the same or very similar date/time
- Are at the same location
- Are updates/revisions of each other

Respond with just the number of the matching event, or 0 if no match."""

        prompt = f"""New event:
Title: {new_event.title}
Date: {new_event.starts_at.isoformat() if new_event.starts_at else 'Unknown'}
Location: {new_event.location or 'Unknown'}

Existing events:
{existing_list}

Which existing event (1-{len(candidates)}) is this a duplicate of? Reply with just the number, or 0 if none."""

        response = await self._call_gemini(prompt, system_prompt)
        
        if not response:
            return None
        
        try:
            match_idx = int(response.strip()) - 1
            if 0 <= match_idx < len(candidates):
                logger.info(f"AI detected duplicate: '{new_event.title}' matches '{candidates[match_idx].title}'")
                return candidates[match_idx]
        except ValueError:
            pass
        
        return None
    
    async def merge_events(self, existing: Event, update: Event) -> Event:
        """
        Intelligently merge an update into an existing event.
        
        Preserves the best information from both, preferring newer data
        where there are conflicts.
        
        Args:
            existing: The existing event in the database
            update: The new version of the event
            
        Returns:
            Merged event with best data from both
        """
        if not self.enabled:
            # Simple merge without AI - prefer update for non-null fields
            if update.title:
                existing.title = update.title
            if update.description:
                existing.description = update.description
            if update.location:
                existing.location = update.location
            if update.starts_at:
                existing.starts_at = update.starts_at
            if update.ends_at:
                existing.ends_at = update.ends_at
            return existing
        
        system_prompt = """You are a data merging assistant for civic events.
Your job is to combine information from two versions of the same event,
keeping the most accurate and complete information.

Rules:
- Prefer more specific/complete information
- Keep newer date/time if they differ
- Combine description details if both have useful info
- Prefer more specific locations

Respond with valid JSON only."""

        prompt = f"""Merge these two versions of the same event:

EXISTING:
Title: {existing.title}
Description: {existing.description or 'None'}
Location: {existing.location or 'Unknown'}
Start: {existing.starts_at.isoformat() if existing.starts_at else 'Unknown'}

UPDATE:
Title: {update.title}
Description: {update.description or 'None'}
Location: {update.location or 'Unknown'}
Start: {update.starts_at.isoformat() if update.starts_at else 'Unknown'}

Return merged JSON with fields: title, description, location
Keep the better/more complete value for each field.

JSON response:"""

        response = await self._call_gemini(prompt, system_prompt)
        
        if not response:
            # Fall back to simple merge
            return await self.merge_events.__wrapped__(self, existing, update)
        
        try:
            data = json.loads(response.strip().removeprefix("```json").removesuffix("```"))
            
            existing.title = data.get("title", existing.title)
            existing.description = data.get("description", existing.description)
            existing.location = data.get("location", existing.location)
            
            # Always use newer time data
            if update.starts_at:
                existing.starts_at = update.starts_at
            if update.ends_at:
                existing.ends_at = update.ends_at
            
            return existing
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse merge response: {e}")
            return existing
    
    async def extract_entities(self, text: str) -> dict:
        """
        Extract named entities from text (people, organizations, locations, dates).
        
        Useful for building a knowledge graph of community stakeholders.
        
        Args:
            text: Text to extract entities from
            
        Returns:
            Dictionary of entity types to lists of entities
        """
        if not self.enabled:
            return {"people": [], "organizations": [], "locations": [], "dates": []}
        
        system_prompt = """You are an entity extraction assistant.
Extract named entities from civic/government text.
Respond with valid JSON only."""

        prompt = f"""Extract entities from this text:

{text[:2000]}

Return JSON with:
- people: list of person names mentioned
- organizations: list of organizations/committees/boards
- locations: list of places/addresses
- dates: list of dates/times mentioned

JSON response:"""

        response = await self._call_gemini(prompt, system_prompt)
        
        if not response:
            return {"people": [], "organizations": [], "locations": [], "dates": []}
        
        try:
            return json.loads(response.strip().removeprefix("```json").removesuffix("```"))
        except json.JSONDecodeError:
            return {"people": [], "organizations": [], "locations": [], "dates": []}
    
    async def validate_event(self, event: Event) -> tuple[bool, list[str]]:
        """
        Validate event data quality using AI.
        
        Checks for:
        - Reasonable dates (not too far past/future)
        - Valid location format
        - Coherent title and description
        - Missing critical information
        
        Args:
            event: Event to validate
            
        Returns:
            Tuple of (is_valid, list of issues found)
        """
        issues = []
        
        # Basic validation (no AI needed)
        if not event.title or len(event.title) < 3:
            issues.append("Title is missing or too short")
        
        if not event.starts_at:
            issues.append("Start time is missing")
        elif event.starts_at.year < 2020 or event.starts_at.year > 2030:
            issues.append(f"Start time {event.starts_at} seems invalid")
        
        # AI-powered validation for more nuanced checks
        if self.enabled and not issues:
            system_prompt = """You are a data validation assistant for civic events.
Check if the event data makes sense and is complete.

Respond with a JSON object:
- valid: true/false
- issues: list of problems found (empty if valid)"""

            prompt = f"""Validate this civic event:

Title: {event.title}
Description: {event.description or 'None'}
Location: {event.location or 'Not specified'}
Start: {event.starts_at.isoformat() if event.starts_at else 'Unknown'}
Type: {event.event_type.value if hasattr(event.event_type, 'value') else event.event_type or 'Unknown'}

Check for:
- Does the title make sense for a civic event?
- Is the description coherent?
- Does the location seem valid?
- Any red flags or spam indicators?

JSON response:"""

            response = await self._call_gemini(prompt, system_prompt)
            
            if response:
                try:
                    data = json.loads(response.strip().removeprefix("```json").removesuffix("```"))
                    if not data.get("valid", True):
                        issues.extend(data.get("issues", []))
                except json.JSONDecodeError:
                    pass
        
        return len(issues) == 0, issues

    async def find_related_events(
        self,
        document_title: str,
        document_content: Optional[str],
        events: list[dict],
        document_date: Optional[str] = None,
        document_type: Optional[str] = None,
        local_path: Optional[str] = None,
    ) -> list[dict]:
        """
        Use AI to find events that should be associated with a document.
        
        Delegates to DocumentLinker for the actual implementation.
        
        Args:
            document_title: Title of the document
            document_content: Optional text content extracted from document
            events: List of event dicts with id, title, start_time, description
            document_date: Optional date associated with the document (published date)
            document_type: Optional type hint (agenda, minutes, attachment, etc.)
            local_path: Optional path to local file for PDF reading if needed
            
        Returns:
            List of dicts with event_id and relationship type
        """
        return await self._linker.find_related_events(
            document_title=document_title,
            document_content=document_content,
            events=events,
            document_date=document_date,
            document_type=document_type,
            local_path=local_path,
        )

    async def generate_event_summary(
        self,
        event: dict,
        sources: list[dict],
        documents: list[dict],
    ) -> Optional[str]:
        """
        Generate an AI overview/summary of an event using all available information.
        
        Delegates to EventSummarizer for the actual implementation.
        
        Args:
            event: Event dict with id, title, description, start_time, location, category
            sources: List of source dicts with name, raw_data
            documents: List of document dicts with title, document_type, relationship, 
                       content_text, local_path
            
        Returns:
            AI-generated summary or None on failure
        """
        return await self._summarizer.generate_summary(
            event=event,
            sources=sources,
            documents=documents,
        )

    async def _extract_pdf_text(self, local_path: str, max_pages: int = 3) -> Optional[str]:
        """
        Extract text from a PDF file for AI analysis.
        
        Delegates to pipeline.ai.pdf_extractor.extract_pdf_text().
        
        Args:
            local_path: Path to the PDF file
            max_pages: Maximum number of pages to extract (to limit token usage)
            
        Returns:
            Extracted text or None if extraction fails
        """
        return await extract_pdf_text(local_path, max_pages)


# Singleton instance for reuse
_processor: Optional[AIEventProcessor] = None


def get_ai_processor() -> AIEventProcessor:
    """Get or create the singleton AI processor instance."""
    global _processor
    if _processor is None:
        _processor = AIEventProcessor()
    return _processor

