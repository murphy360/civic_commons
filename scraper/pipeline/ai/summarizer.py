"""
AI-powered event summary generation.

This module generates concise, helpful summaries of civic events
using all available information (event details, sources, documents).
"""

import logging
from typing import Optional

from .client import GeminiClient
from .pdf_extractor import extract_pdf_text

logger = logging.getLogger("civic.ai.summarizer")


# System prompt for meeting summaries
MEETING_SYSTEM_PROMPT = """You are a civic information assistant helping residents understand local government meetings.

Your job is to create a concise, helpful summary of a government meeting based on available documents.

FOCUS ON:
- Non-routine agenda items (skip standard approvals like minutes approval, roll call)
- Key decisions, votes, or discussions
- Public hearing items
- New business or special presentations
- Items that directly affect residents

SKIP or briefly mention:
- Routine procedural items (call to order, roll call, adjournment)
- Standard consent agenda items unless notable
- Minutes approval from previous meetings

FORMAT:
- Start with a one-sentence overview
- Use bullet points for key items
- Keep it under 200 words
- Be factual and neutral
- If agenda only, say "Scheduled to discuss:" 
- If minutes available, say "Discussed:" or "Decided:" """


# System prompt for community event summaries
COMMUNITY_EVENT_SYSTEM_PROMPT = """You are a civic information assistant helping residents learn about community events.

Your job is to create a helpful, engaging summary of a community event.

INCLUDE:
- What the event is about
- Who it's for (families, seniors, all ages, etc.)
- Key details like registration requirements or things to bring
- Why someone might want to attend

FORMAT:
- Start with an engaging one-sentence hook
- Include practical details
- Keep it under 150 words
- Be warm and inviting but factual"""


class EventSummarizer:
    """
    AI-powered event summary generation.
    
    Generates concise summaries of civic events, with special handling
    for government meetings (focusing on non-routine items) vs community
    events (focusing on engagement and practical details).
    """
    
    def __init__(self, client: GeminiClient):
        """
        Initialize the event summarizer.
        
        Args:
            client: GeminiClient instance for API calls
        """
        self._client = client
    
    @property
    def enabled(self) -> bool:
        """Check if summarization is enabled."""
        return self._client.enabled
    
    async def generate_summary(
        self,
        event: dict,
        sources: list[dict],
        documents: list[dict],
    ) -> Optional[str]:
        """
        Generate an AI overview/summary of an event using all available information.
        
        For meetings with agendas/minutes, focuses on non-routine items.
        For community events, provides a helpful overview.
        
        Args:
            event: Event dict with id, title, description, start_time, location, category
            sources: List of source dicts with name, raw_data
            documents: List of document dicts with title, document_type, relationship, 
                       content_text, local_path
            
        Returns:
            AI-generated summary or None on failure
        """
        if not self.enabled:
            logger.warning("AI not enabled - cannot generate event summary")
            return None
        
        # Determine if this is a meeting (has agenda/minutes)
        is_meeting = self._is_meeting(documents)
        
        # Build context
        source_info = self._build_source_info(sources)
        doc_content = await self._build_document_content(documents)
        
        # Choose appropriate system prompt
        system_prompt = (
            MEETING_SYSTEM_PROMPT if is_meeting 
            else COMMUNITY_EVENT_SYSTEM_PROMPT
        )
        
        # Build the prompt
        prompt = self._build_prompt(event, source_info, doc_content)
        
        response = await self._client.generate(prompt, system_prompt)
        
        if response:
            summary = self._clean_response(response)
            logger.info(
                f"Generated AI summary for event '{event.get('title')}' "
                f"({len(summary)} chars)"
            )
            return summary
        
        return None
    
    def _is_meeting(self, documents: list[dict]) -> bool:
        """Check if event is a meeting based on document types."""
        return any(
            d.get('relationship') in ('agenda', 'minutes', 'packet') 
            for d in documents
        )
    
    def _build_source_info(self, sources: list[dict]) -> list[str]:
        """Build source information strings."""
        source_info = []
        for src in sources:
            info = f"- {src.get('name', 'Unknown source')}"
            if src.get('raw_data'):
                raw = src['raw_data']
                if isinstance(raw, dict):
                    desc = raw.get('description')
                    if desc:
                        info += f"\n  Description: {desc[:500]}"
            source_info.append(info)
        return source_info
    
    async def _build_document_content(self, documents: list[dict]) -> list[str]:
        """
        Build document content strings for event summary.
        
        Prioritizes pre-generated AI summaries over raw content to avoid
        repeated PDF parsing and summarization.
        """
        doc_content = []
        for doc in documents:
            doc_info = (
                f"### {doc.get('title', 'Untitled')} "
                f"({doc.get('relationship', 'related')})"
            )
            
            # Priority 1: Use pre-generated AI summary (most efficient)
            content = doc.get('ai_summary')
            
            # Priority 2: Use raw content_text if no AI summary
            if not content:
                content = doc.get('content_text')
            
            # Priority 3: Extract from PDF as last resort
            if not content and doc.get('local_path'):
                logger.debug(f"No AI summary for '{doc.get('title')}', extracting PDF")
                content = await extract_pdf_text(doc['local_path'], max_pages=5)
            
            if content:
                # Truncate - AI summaries are already concise, raw content needs more truncation
                max_chars = 500 if doc.get('ai_summary') else 3000
                doc_info += f"\n{content[:max_chars]}"
            
            doc_content.append(doc_info)
        return doc_content
    
    def _build_prompt(
        self,
        event: dict,
        source_info: list[str],
        doc_content: list[str],
    ) -> str:
        """Build the summary generation prompt."""
        description = event.get('description') or 'No description available'
        return f"""Create a summary for this event:

**{event.get('title', 'Untitled Event')}**
- Date: {event.get('start_time', 'TBD')}
- Location: {event.get('location', 'Not specified')}
- Category: {event.get('category', 'General')}

Original Description:
{description[:500]}

Sources:
{chr(10).join(source_info) if source_info else 'No additional source information'}

Documents:
{chr(10).join(doc_content) if doc_content else 'No documents available'}

Generate a concise, helpful summary:"""
    
    def _clean_response(self, response: str) -> str:
        """Clean up the AI response."""
        summary = response.strip()
        
        # Remove any markdown code blocks if present
        if summary.startswith("```"):
            summary = summary.split("```")[1]
            if summary.startswith("markdown") or summary.startswith("text"):
                summary = summary.split("\n", 1)[1] if "\n" in summary else summary
        
        return summary.strip()
