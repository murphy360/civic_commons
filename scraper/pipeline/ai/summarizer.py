"""
AI-powered event summary generation.

This module generates concise, helpful summaries of civic events
using all available information (event details, sources, documents).

The summaries are designed for the "average citizen" - providing a 30-second
readable overview that helps residents:
- Quickly understand what happened or will happen
- Identify topics of personal interest worth digging into
- Know if any actions affect them (deadlines, changes, decisions)
"""

import logging
import re
from datetime import datetime
from typing import Optional
from collections import defaultdict

from .client import GeminiClient, MODELS
from .pdf_extractor import extract_pdf_text

logger = logging.getLogger("civic.ai.summarizer")


# System prompt for meeting summaries - citizen-focused, substance-first
MEETING_SYSTEM_PROMPT = """You are extracting KEY SUBSTANCE from government meeting documents for busy residents.

DO NOT write marketing fluff. DO NOT repeat date/time/location. DO NOT invite participation.

YOUR JOB: Extract ACTUAL CONTENT that matters to residents.

**LEAD WITH PUBLIC CONCERN** (MOST IMPORTANT):
Start EVERY summary with a one-line indicator of public engagement level:

🔴 **Heated:** "Residents voiced strong concerns about [topic]. [X] speakers addressed council."
🟡 **Mixed:** "Some public comment on [topic]; council discussion was [brief/extended]."
🟢 **Routine:** "No public comments. Standard agenda items processed."

If video analysis shows public comments, debates, or contentious votes - LEAD WITH THAT.
This tells busy residents whether they should read further.

FOR EACH ORDINANCE/RESOLUTION YOU MENTION:
- Include the number (e.g., "Ord. 115-2025")
- ALWAYS explain what it does in plain language (REQUIRED - never list numbers without descriptions)
- Note which reading (1st, 2nd, 3rd/final)
- Vote result if available ("Passed 5-2", "Tabled", etc.)

BAD: "Ordinances 115-2025 through 118-2025 discussed" (no descriptions!)
GOOD: "Ord. 115-2025 (2026 budget appropriations), Ord. 116-2025 (new cybersecurity policy)"

OTHER PRIORITY ITEMS:
- Money/contracts over $10K with dollar amounts
- Zoning changes with addresses
- Items tabled or referred to committee (often signals controversy)
- Split votes (not unanimous) - these indicate disagreement

FROM VIDEO RECORDINGS (if included):
- Public comments: who spoke and what concerns they raised
- Debates: what topics had disagreement or discussion
- Vote results mentioned in the video
- Tone/sentiment: was anything contentious?

IF AMENDMENTS EXIST (between agenda versions):
When original and amended versions of an agenda/minutes are provided, specifically note what was ADDED or CHANGED.

NOTE: Video titles changing does NOT mean the agenda was amended. Videos are just recordings of the meeting.

FORMAT:
1. **First line**: Public concern indicator (🔴/🟡/🟢 with brief explanation)
2. **Second**: Key topic(s) that drew attention (if any)
3. **Then**: Bullet list of ordinances/resolutions with descriptions
4. 100-250 words total
5. Skip routine procedural items (roll call, minutes approval)

If only procedural items and no public comment:
"🟢 **Routine:** No public comments. Approved previous minutes, no major ordinances or controversial votes."

NO fluff. NO engagement language."""


# System prompt for community event summaries - brief and practical
COMMUNITY_EVENT_SYSTEM_PROMPT = """Extract the key details of this community event. Be brief and practical.

DO NOT write marketing fluff. DO NOT say "Want to..." or "Join us for..."

GOOD: "Free outdoor concert featuring local jazz bands. Bring lawn chairs. Food trucks on site. Kids welcome."

BAD: "Looking for something fun to do? Join us for an exciting evening of music and community!"

INCLUDE ONLY:
- What it is (1 sentence)
- Who it's for (families, seniors, all ages)
- Cost (free or $X)
- What to bring/know
- Registration required? 

FORMAT: 2-4 short sentences or bullets. Under 75 words."""


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
        
        For meetings with agendas/minutes, focuses on non-routine items and
        highlights any amendments/changes between document versions.
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
        
        # Build context (now returns tuple with amendments note)
        source_info = self._build_source_info(sources)
        doc_content, amendments_note = await self._build_document_content(documents)
        
        # Choose appropriate system prompt
        system_prompt = (
            MEETING_SYSTEM_PROMPT if is_meeting 
            else COMMUNITY_EVENT_SYSTEM_PROMPT
        )
        
        # Build the prompt (now includes amendments note and documents for source attribution)
        prompt = self._build_prompt(event, source_info, doc_content, amendments_note, documents)
        
        model = "flash"  # EventSummarizer uses flash model
        response = await self._client.generate(prompt, system_prompt, model=model)
        
        if response:
            summary = self._clean_response(response)
            
            # Add generation footer
            today = datetime.now().strftime("%B %d, %Y")
            model_name = MODELS.get(model, "").split("/models/")[1].split(":")[0] if "/models/" in MODELS.get(model, "") else model
            footer = f"\n\n---\n*Generated: {today} by {model_name}*"
            summary = summary + footer
            
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
    
    async def _build_document_content(self, documents: list[dict]) -> tuple[list[str], str]:
        """
        Build document content strings for event summary.
        
        Prioritizes pre-generated AI summaries over raw content to avoid
        repeated PDF parsing and summarization.
        
        Also identifies document versions (original vs amended) and prepares
        a comparison note if multiple versions exist.
        
        Video documents are given special treatment - their AI summaries often
        contain rich analysis (public comments, debates, sentiment) that should
        be surfaced in the event summary.
        
        Returns:
            Tuple of (doc_content list, amendments_note string)
        """
        doc_content = []
        video_content = []  # Separate list for videos to prioritize their analysis
        
        # Group documents by type and base title to identify versions
        doc_groups = self._group_document_versions(documents)
        amendments_note = self._build_amendments_note(doc_groups, documents)
        
        for doc in documents:
            rel = doc.get('relationship', 'related')
            is_video = rel == 'video'
            
            doc_info = (
                f"### {doc.get('title', 'Untitled')} "
                f"({rel})"
            )
            
            # Priority 1: Use pre-generated AI summary (most efficient)
            content = doc.get('ai_summary')
            
            # Priority 2: Use raw content_text if no AI summary
            if not content:
                content = doc.get('content_text')
            
            # Priority 3: Extract from PDF as last resort (not for videos)
            if not content and doc.get('local_path') and not is_video:
                logger.debug(f"No AI summary for '{doc.get('title')}', extracting PDF")
                content = await extract_pdf_text(doc['local_path'], max_pages=5)
            
            if content:
                # Videos get more space since their AI summaries contain rich analysis
                # (public comments, debates, sentiment, etc.)
                if is_video:
                    max_chars = 2000  # Video summaries are valuable - include more
                    doc_info = f"### VIDEO RECORDING: {doc.get('title', 'Untitled')}\n"
                    doc_info += "(Contains meeting recording analysis - public comments, debates, votes)\n"
                elif doc.get('ai_summary'):
                    max_chars = 500  # AI summaries are already concise
                else:
                    max_chars = 3000  # Raw content needs more space
                    
                doc_info += f"\n{content[:max_chars]}"
            
            # Sort videos to front for priority
            if is_video:
                video_content.append(doc_info)
            else:
                doc_content.append(doc_info)
        
        # Put video content first so the AI sees the rich analysis prominently
        all_content = video_content + doc_content
        
        return all_content, amendments_note
    
    def _group_document_versions(self, documents: list[dict]) -> dict:
        """
        Group documents by their base type to identify original vs amended versions.
        
        Documents with the same relationship type (agenda, minutes) for the same
        event may represent different versions if there are multiple.
        
        NOTE: Excludes 'video' relationship type - multiple videos are not amendments,
        they are separate recordings (e.g., Caucus Meeting vs Regular Meeting).
        
        Returns:
            Dict mapping relationship type to list of documents of that type
        """
        # Relationship types that CAN have amendments (original vs amended versions)
        AMENDABLE_TYPES = {'agenda', 'minutes', 'packet'}
        
        groups = defaultdict(list)
        for doc in documents:
            rel = doc.get('relationship', 'related')
            # Only group amendable types - videos are not amendments
            if rel in AMENDABLE_TYPES:
                groups[rel].append(doc)
        return dict(groups)
    
    def _build_amendments_note(self, doc_groups: dict, documents: list[dict]) -> str:
        """
        Build a detailed note about document amendments/versions if multiple exist.
        
        Compares content between original and amended versions to identify changes.
        
        Args:
            doc_groups: Dict mapping relationship type to list of documents
            documents: Full list of documents with content
        
        Returns:
            String with amendment details, or empty string if no amendments
        """
        notes = []
        
        for rel_type, docs in doc_groups.items():
            if len(docs) > 1:
                # Multiple documents of same type = versions
                # Sort by title to get original vs amended order
                sorted_docs = sorted(docs, key=lambda d: 'amend' in d.get('title', '').lower())
                
                original = sorted_docs[0]
                amended_list = sorted_docs[1:]
                
                type_name = rel_type.replace('_', ' ').title()
                
                # Build comparison info
                orig_title = original.get('title', 'Original')
                orig_content = original.get('ai_summary') or original.get('content_text') or ''
                
                for amended in amended_list:
                    amend_title = amended.get('title', 'Amended')
                    amend_content = amended.get('ai_summary') or amended.get('content_text') or ''
                    
                    note = f"DOCUMENT VERSIONS ({type_name}):\n"
                    note += f"- Original: {orig_title}\n"
                    note += f"- Amended: {amend_title}\n"
                    
                    # Include both contents for AI to compare
                    if orig_content and amend_content:
                        note += f"\nORIGINAL CONTENT:\n{orig_content[:1500]}\n"
                        note += f"\nAMENDED CONTENT:\n{amend_content[:1500]}\n"
                        note += "\nCompare these and note what was ADDED, REMOVED, or CHANGED."
                    
                    notes.append(note)
        
        return "\n\n".join(notes) if notes else ""
    
    def _build_prompt(
        self,
        event: dict,
        source_info: list[str],
        doc_content: list[str],
        amendments_note: str = "",
        documents: list[dict] = None,
    ) -> str:
        """Build the summary generation prompt with citizen-focused framing."""
        description = event.get('description') or 'No description available'
        
        # Build the amendments section if there are any
        amendments_section = ""
        if amendments_note:
            amendments_section = f"""
⚠️ DOCUMENT AMENDMENTS - COMPARE AND DESCRIBE CHANGES:
{amendments_note}
"""
        
        # Build document source list for attribution
        doc_list = ""
        if documents:
            doc_titles = [d.get('title', 'Untitled') for d in documents if d.get('title')]
            if doc_titles:
                doc_list = "\n\nDOCUMENTS USED: " + ", ".join(doc_titles)
        
        return f"""Extract key substance from this government meeting:

**{event.get('title', 'Untitled Event')}**

Original Description:
{description[:500]}
{amendments_section}
Document Content:
{chr(10).join(doc_content) if doc_content else 'No documents available'}

REQUIREMENTS:
1. For EVERY ordinance/resolution mentioned, include its number AND what it does
2. If amendments exist above, describe what changed between versions
3. Include vote results if available
4. End with: "Sources: [list document titles used]"

Generate summary:"""
    
    def _clean_response(self, response: str) -> str:
        """Clean up the AI response."""
        summary = response.strip()
        
        # Remove any markdown code blocks if present
        if summary.startswith("```"):
            summary = summary.split("```")[1]
            if summary.startswith("markdown") or summary.startswith("text"):
                summary = summary.split("\n", 1)[1] if "\n" in summary else summary
        
        return summary.strip()
