"""
AI-powered document summary generation.

This module generates concise summaries of civic documents (agendas, minutes,
flyers, etc.) during download. These summaries are stored in the database
and reused for event summaries to avoid repeated processing.
"""

import logging
from typing import Optional

from .client import GeminiClient
from .pdf_extractor import extract_pdf_text

logger = logging.getLogger("civic.ai.doc_summarizer")


# System prompt for meeting documents (agendas, minutes, packets)
MEETING_DOC_SYSTEM_PROMPT = """You are extracting KEY SUBSTANCE from government meeting documents.

DO NOT write fluffy introductions. Get straight to the content.

For AGENDAS, extract:
1. ORDINANCES - List each with:
   - Number (e.g., "Ord. 2025-42")
   - What it does in plain language
   - Which reading (1st, 2nd, 3rd/final)
   
2. RESOLUTIONS - Same format as ordinances

3. PUBLIC HEARINGS - What they're about, addresses if zoning-related

4. NEW BUSINESS - Specific items, not "various matters"

5. MONEY ITEMS - Dollar amounts, contracts, budget items

For MINUTES, extract:
1. VOTES - What passed/failed, vote counts (e.g., "5-2"), who dissented
2. Final readings that passed
3. Items tabled or continued
4. Key discussion points with specifics

SKIP: Roll call, minutes approval, adjournment, pledge, routine procedural items

FORMAT EXAMPLE:
"City Council Agenda - Dec 9, 2025
• Ord. 2025-42 (3rd reading): 3% water rate increase effective Jan 1
• Ord. 2025-45 (1st reading): Rezone 123 Oak St from R-1 to Mixed Use  
• Resolution 2025-18: Approve $85K contract for Elm Ave sidewalks
• Public Hearing: Proposed dog park at Memorial Field"

Keep under 200 words. Be specific with numbers, addresses, amounts."""


# System prompt for general documents (flyers, guides, forms)
GENERAL_DOC_SYSTEM_PROMPT = """Summarize this government document with SPECIFIC details.

EXTRACT:
- What it's about (one sentence)
- Key dates, deadlines, requirements
- Dollar amounts, fees, costs if mentioned
- Who is affected and how

NO fluff. Get to the point. Under 150 words."""


# System prompt for meeting video recordings
VIDEO_MEETING_SYSTEM_PROMPT = """You are analyzing a government meeting video to capture what ISN'T in official minutes.

Official minutes record votes and motions. Your job is to capture the HUMAN DYNAMICS:

1. PUBLIC COMMENTS & CONCERNS
   - What issues did residents raise?
   - What emotions were expressed (frustration, support, fear, hope)?
   - Were there recurring themes across multiple speakers?
   - Note approximate timestamps for significant comments (e.g., "~15:30")

2. COUNCIL/BOARD MEMBER DYNAMICS
   - Who asked tough questions? About what?
   - Were there disagreements between members? On what topics?
   - Did anyone express reservations before voting yes?
   - Who championed or opposed specific items?

3. HEATED OR NOTABLE MOMENTS
   - Any debates that got tense? What sparked them?
   - Moments of humor or levity?
   - Surprising statements or admissions?
   - Times when officials seemed caught off guard?

4. BETWEEN-THE-LINES INSIGHTS
   - What concerns seemed to influence decisions even if not explicitly stated?
   - Items that got rushed through vs. extensively discussed?
   - Body language moments (sighs, frustration, enthusiasm)?

5. TIMESTAMPS FOR KEY MOMENTS
   - Note approximate video timestamps for moments viewers might want to see
   - Format: "~1:23:45 - Council debate on zoning variance gets heated"

FORMAT:
**Meeting Tone:** [One sentence overall characterization]

**Key Concerns Raised:**
• [Concern] (~timestamp)

**Notable Exchanges:**
• [Who vs who, about what] (~timestamp)

**Worth Watching:**
• [Timestamp] - [Brief description of why]

200-400 words. Focus on what you can ONLY learn from watching, not reading minutes.
If it's a routine meeting with no drama, say so: "Procedural meeting with minimal discussion."

NO vote tallies (that's in minutes). NO ordinance descriptions (that's in agendas). 
Capture the FEEL of the room."""


class DocumentSummarizer:
    """
    AI-powered document summary generation.
    
    Generates summaries during document download that are stored in the DB
    and reused for event summaries.
    """
    
    def __init__(self, client: GeminiClient):
        """
        Initialize the document summarizer.
        
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
        title: str,
        document_type: Optional[str] = None,
        content_text: Optional[str] = None,
        local_path: Optional[str] = None,
        video_url: Optional[str] = None,
        max_content_chars: int = 5000,
    ) -> Optional[str]:
        """
        Generate an AI summary of a document.
        
        Args:
            title: Document title
            document_type: Type hint (agenda, minutes, flyer, video, etc.)
            content_text: Pre-extracted text content
            local_path: Path to local file for PDF extraction if no content
            video_url: YouTube URL for video documents
            max_content_chars: Maximum characters to send to AI
            
        Returns:
            AI-generated summary or None on failure
        """
        if not self.enabled:
            logger.debug("AI not enabled - skipping document summary")
            return None
        
        # Handle YouTube videos specially
        if document_type == 'video' and video_url:
            return await self._summarize_video(title, video_url)
        
        # Get content for text-based documents
        content = content_text
        if not content and local_path:
            content = await extract_pdf_text(local_path, max_pages=10)
        
        if not content:
            logger.debug(f"No content available for document '{title}'")
            return None
        
        # Truncate content
        content = content[:max_content_chars]
        
        # Determine document category
        is_meeting_doc = self._is_meeting_document(title, document_type)
        system_prompt = (
            MEETING_DOC_SYSTEM_PROMPT if is_meeting_doc 
            else GENERAL_DOC_SYSTEM_PROMPT
        )
        
        # Build prompt
        prompt = self._build_prompt(title, document_type, content)
        
        response = await self._client.generate(prompt, system_prompt)
        
        if response:
            summary = self._clean_response(response)
            logger.info(
                f"Generated AI summary for document '{title}' "
                f"({len(summary)} chars)"
            )
            return summary
        
        return None
    
    async def _summarize_video(self, title: str, video_url: str) -> Optional[str]:
        """
        Generate AI summary of a YouTube video using Gemini's video analysis.
        
        Args:
            title: Video title
            video_url: YouTube URL
            
        Returns:
            AI-generated summary or None on failure
        """
        logger.info(f"Summarizing video: {title} ({video_url})")
        
        prompt = f"""Analyze this government meeting video recording.

Video Title: {title}

I need you to capture what WON'T be in the official minutes:
- The mood and tone of the meeting
- Concerns and emotions expressed by residents during public comment
- Debates or tensions between council/board members
- Questions that revealed uncertainty or pushback
- Moments worth watching with approximate timestamps

Help viewers decide if they should watch specific sections of this meeting."""
        
        response = await self._client.generate_with_video(
            prompt=prompt,
            video_url=video_url,
            system_prompt=VIDEO_MEETING_SYSTEM_PROMPT,
        )
        
        if response:
            summary = self._clean_response(response)
            logger.info(
                f"Generated AI video summary for '{title}' "
                f"({len(summary)} chars)"
            )
            return summary
        
        logger.warning(f"Failed to generate video summary for '{title}'")
        return None
    
    def _is_meeting_document(
        self,
        title: str,
        document_type: Optional[str],
    ) -> bool:
        """Check if this is a meeting-related document."""
        meeting_keywords = [
            'agenda', 'minutes', 'packet', 'meeting', 
            'council', 'board', 'commission', 'committee'
        ]
        
        title_lower = title.lower()
        type_lower = (document_type or '').lower()
        
        return any(
            kw in title_lower or kw in type_lower 
            for kw in meeting_keywords
        )
    
    def _build_prompt(
        self,
        title: str,
        document_type: Optional[str],
        content: str,
    ) -> str:
        """Build the summarization prompt."""
        type_info = f" (Type: {document_type})" if document_type else ""
        
        return f"""Document: **{title}**{type_info}

CONTENT:
{content}

---
Extract the KEY SUBSTANCE following the system instructions. No intro, just facts:"""
    
    def _clean_response(self, response: str) -> str:
        """Clean up the AI response."""
        summary = response.strip()
        
        # Remove any markdown code blocks if present
        if summary.startswith("```"):
            parts = summary.split("```")
            if len(parts) >= 2:
                summary = parts[1]
                if summary.startswith("markdown") or summary.startswith("text"):
                    summary = summary.split("\n", 1)[1] if "\n" in summary else summary
        
        return summary.strip()
