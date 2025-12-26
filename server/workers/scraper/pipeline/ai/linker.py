"""
AI-powered document-to-event linking.

This module provides intelligent document linking that matches documents
(agendas, minutes, flyers, etc.) to relevant civic events.
"""

import json
import logging
from typing import Optional

from .client import GeminiClient
from .pdf_extractor import extract_pdf_text

logger = logging.getLogger("civic.ai.linker")


# System prompt for document linking
LINKER_SYSTEM_PROMPT = """You are a secretary for a local government office. Your job is to organize documents and link them to the correct events.

When you receive a document, you must:
1. Review the document title, date, and any content
2. Look at the list of upcoming events  
3. Determine which events (if any) the document relates to

CRITICAL RULES:
- AGENDAS, MINUTES, and VIDEOS must link to exactly ONE meeting event (the specific meeting they are for)
- Use dates to match: an agenda dated "November 17, 2025" should link to a meeting on that date
- YouTube videos are RECORDINGS of specific meetings - find the ONE meeting they belong to
- Flyers, guidelines, and program materials CAN link to multiple events (e.g., all sessions of a recurring class)

Match documents to events based on:
- DATE ALIGNMENT: Match document dates to event dates (most important for agendas/minutes/videos)
- Event name similarity (e.g., "Kids Yoga Flyer" → "Kids' Yoga with Yoga Squirrel")  
- Topic/activity alignment
- Program or series connections (for recurring events)

Relationship types:
- "agenda": Document is an agenda for a specific meeting (LINK TO ONE EVENT ONLY)
- "minutes": Document contains minutes from a specific meeting (LINK TO ONE EVENT ONLY)
- "video": Document is a video recording of a specific meeting (LINK TO ONE EVENT ONLY)
- "attachment": Document is related material (flyers, guidelines, forms) - can link to multiple
- "packet": Document is a meeting packet (LINK TO ONE EVENT ONLY)

Always respond with valid JSON only."""


class DocumentLinker:
    """
    AI-powered document-to-event linking.
    
    Acts as an intelligent secretary that reviews documents and matches them
    to relevant events based on title, content, dates, and context.
    """
    
    def __init__(self, client: GeminiClient):
        """
        Initialize the document linker.
        
        Args:
            client: GeminiClient instance for API calls
        """
        self._client = client
    
    @property
    def enabled(self) -> bool:
        """Check if linking is enabled."""
        return self._client.enabled
    
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
        if not self.enabled:
            logger.warning("AI not enabled - cannot find related events")
            return []
        
        if not events:
            return []
        
        # For agendas, minutes, and videos - pre-filter to only events with matching dates
        # This is the most important rule: these document types must match event dates exactly
        filtered_events = events
        is_date_specific_doc = document_type and document_type.lower() in ('agenda', 'minutes', 'video')
        
        if is_date_specific_doc and document_date:
            # Parse document date and filter events to only those matching the date
            doc_date_str = document_date[:10]  # Get just YYYY-MM-DD part
            filtered_events = [
                e for e in events
                if e.get('start_time', '').startswith(doc_date_str)
            ]
            
            if not filtered_events:
                logger.info(
                    f"No events found matching date {doc_date_str} for {document_type} "
                    f"'{document_title}' - skipping AI linking"
                )
                return []
            
            logger.debug(
                f"Pre-filtered {len(events)} events to {len(filtered_events)} "
                f"matching date {doc_date_str}"
            )
        
        # Format events list for the prompt
        events_text = "\n".join([
            f"- Event ID {e['id']}: \"{e['title']}\" on {e['start_time']}"
            for e in filtered_events[:50]  # Limit to 50 events to avoid token limits
        ])
        
        # Build document context
        doc_context_parts = [f'Document Title: "{document_title}"']
        
        if document_date:
            doc_context_parts.append(f"Document Date: {document_date}")
        
        if document_type:
            doc_context_parts.append(f"Document Type: {document_type}")
        
        doc_context = "\n".join(doc_context_parts)
        
        # Get content preview
        content_preview = await self._get_content_preview(
            document_content, local_path
        )
        
        prompt = f"""A new document has arrived that needs to be filed.

{doc_context}{content_preview}

Upcoming Events:
{events_text}

Which events should this document be linked to?

CRITICAL DATE MATCHING RULES:
- For AGENDA documents: The document date MUST match the event date. An agenda for "January 28, 2025" ONLY links to events on January 28, 2025.
- For MINUTES documents: The document date MUST match the event date. Minutes from "March 25, 2025" ONLY links to events on March 25, 2025.
- For VIDEO documents: Link to exactly ONE meeting that matches the date in the document title/content.
- If the document date does NOT match any event date exactly, return an EMPTY matches array.
- General attachments/flyers without specific meeting dates can match multiple events.

The document date "{document_date}" should match the event start_time date exactly for agendas/minutes.

Return a JSON object with:
- matches: array of objects with "event_id" (number) and "relationship" (string: "agenda", "minutes", "video", "packet", or "attachment")
- reasoning: brief explanation of why these events match (or why no match - be specific about date mismatch if applicable)

If no events match the date, return an empty matches array.

JSON response:"""

        response = await self._client.generate(prompt, LINKER_SYSTEM_PROMPT)
        
        if not response:
            return []
        
        return self._parse_response(response, filtered_events, document_title)
    
    async def _get_content_preview(
        self,
        document_content: Optional[str],
        local_path: Optional[str],
    ) -> str:
        """Get content preview from text or PDF."""
        if document_content:
            return f"\n\nDocument content preview:\n{document_content[:1500]}"
        
        if local_path:
            pdf_text = await extract_pdf_text(local_path)
            if pdf_text:
                return f"\n\nDocument content (extracted from PDF):\n{pdf_text[:1500]}"
        
        return ""
    
    def _parse_response(
        self,
        response: str,
        events: list[dict],
        document_title: str,
    ) -> list[dict]:
        """Parse and validate the AI response."""
        try:
            # Parse JSON response
            data = json.loads(
                response.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
            )
            
            matches = data.get("matches", [])
            reasoning = data.get("reasoning", "")
            
            if matches:
                logger.info(
                    f"AI found {len(matches)} event matches for document "
                    f"'{document_title}': {reasoning}"
                )
            else:
                logger.debug(
                    f"AI found no event matches for document "
                    f"'{document_title}': {reasoning}"
                )
            
            # Validate that returned event IDs exist in our events list
            valid_ids = {e['id'] for e in events}
            validated_matches = [
                m for m in matches 
                if m.get('event_id') in valid_ids and m.get('relationship')
            ]
            
            # Enforce single-event rule for agendas and minutes
            validated_matches = self._enforce_single_event_rule(validated_matches)
            
            return validated_matches
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse AI response for document linking: {e}")
            return []
    
    def _enforce_single_event_rule(self, matches: list[dict]) -> list[dict]:
        """Ensure agendas/minutes/videos only link to one event."""
        # These document types should only link to ONE specific meeting
        single_event_types = ('agenda', 'minutes', 'packet', 'video')
        
        single_matches = [
            m for m in matches 
            if m.get('relationship') in single_event_types
        ]
        
        if len(single_matches) > 1:
            logger.warning(
                f"AI returned {len(single_matches)} matches for single-event document type - "
                "keeping only first match"
            )
            other_matches = [
                m for m in matches 
                if m.get('relationship') not in single_event_types
            ]
            return [single_matches[0]] + other_matches
        
        return matches

