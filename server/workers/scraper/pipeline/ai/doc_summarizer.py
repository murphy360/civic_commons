"""
AI-powered document summary generation.

This module generates concise summaries of civic documents (agendas, minutes,
flyers, etc.) during download. These summaries are stored in the database
and reused for event summaries to avoid repeated processing.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from .client import GeminiClient, MODELS
from .pdf_extractor import extract_pdf_text

logger = logging.getLogger("civic.ai.doc_summarizer")


@dataclass
class SummaryResult:
    """Result from summary generation, including the model used."""
    text: str
    model: str  # Model key (e.g., 'flash', 'flash-2.5', 'pro')
    
    @property
    def model_name(self) -> str:
        """Get the full model name from the URL."""
        url = MODELS.get(self.model, "")
        # Extract model name from URL like ".../gemini-2.5-flash:generateContent"
        if "/models/" in url:
            return url.split("/models/")[1].split(":")[0]
        return self.model
    
    @property
    def text_with_footer(self) -> str:
        """Get the summary text with a generation footer."""
        today = datetime.now().strftime("%B %d, %Y")
        footer = f"\n\n---\n*Generated: {today} by {self.model_name}*"
        return self.text + footer


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

IMPORTANT LENGTH REQUIREMENT: Generate 300-600 words minimum. This is the PRIMARY SUMMARY for the document and will be read by many people. Do NOT be overly brief.
Be specific with numbers, addresses, amounts. Include all significant items."""


# System prompt for general documents (flyers, guides, forms)
GENERAL_DOC_SYSTEM_PROMPT = """Summarize this government document with SPECIFIC details.

EXTRACT:
- What it's about (one sentence)
- Key dates, deadlines, requirements
- Dollar amounts, fees, costs if mentioned
- Who is affected and how

Generate 200-400 words. Be specific. Do NOT be overly brief. This is the primary summary for the document and will be read by the public."""


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
    ) -> Optional[SummaryResult]:
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
            SummaryResult with text and model info, or None on failure
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
        
        # Use flash model for document summaries
        model = "flash"
        response = await self._client.generate(prompt, system_prompt, model=model)
        
        if response:
            summary = self._clean_response(response)
            logger.info(
                f"Generated AI summary for document '{title}' "
                f"({len(summary)} chars) using {model}"
            )
            return SummaryResult(text=summary, model=model)
        
        return None
    
    async def _summarize_video(self, title: str, video_url: str) -> Optional[SummaryResult]:
        """
        Generate AI summary of a YouTube video using Gemini's video analysis.
        
        Args:
            title: Video title
            video_url: YouTube URL
            
        Returns:
            SummaryResult with text and model info, or None on failure
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
        
        # Use flash-2.5 model for video analysis
        model = "flash-2.5"
        response = await self._client.generate_with_video(
            prompt=prompt,
            video_url=video_url,
            system_prompt=VIDEO_MEETING_SYSTEM_PROMPT,
        )
        
        if response:
            summary = self._clean_response(response)
            logger.info(
                f"Generated AI video summary for '{title}' "
                f"({len(summary)} chars) using {model}"
            )
            return SummaryResult(text=summary, model=model)
        
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
    
    async def extract_legislation(
        self,
        title: str,
        document_type: Optional[str] = None,
        content_text: Optional[str] = None,
        local_path: Optional[str] = None,
        max_content_chars: int = 5000,
    ) -> Optional[list[dict]]:
        """
        Extract legislation mentions from a document.
        
        Returns a list of legislation mentions with details.
        
        Args:
            title: Document title
            document_type: Type hint (agenda, minutes, etc.)
            content_text: Pre-extracted text content
            local_path: Path to local file for PDF extraction if no content
            max_content_chars: Maximum characters to send to AI
            
        Returns:
            List of legislation dictionaries or None on failure
        """
        if not self.enabled:
            logger.debug("AI not enabled - skipping legislation extraction")
            return None
        
        # Get content for text-based documents
        content = content_text
        if not content and local_path:
            content = await extract_pdf_text(local_path, max_pages=10)
        
        if not content:
            logger.debug(f"No content available for legislation extraction from '{title}'")
            return None
        
        # Truncate content
        content = content[:max_content_chars]
        
        prompt = f"""Document: **{title}**

CONTENT:
{content}

---
Extract ALL LEGISLATION MENTIONS from this document. For each one, format as a single line:

TYPE|NUMBER|TITLE|ACTION|VOTE_RESULT|VOTE_DETAILS|EXCERPT

IMPORTANT FORMATTING RULES:
- TYPE: Must be ONE of: ordinance, resolution, motion, bylaw, proclamation (lowercase)
- NUMBER: The legislation identifier only (e.g., "2025-139", "R-2025-12", "118-25")
- TITLE: Full name/title if available (or "N/A")
- ACTION: Must be EXACTLY ONE of (lowercase): introduced, first_reading, second_reading, third_reading, public_hearing, amended, tabled, referred, approved, adopted, failed, vetoed, withdrawn, discussed
  * CRITICAL: Choose the PRIMARY action. If multiple actions occurred, pick the most recent/final one.
  * Do NOT use comma-separated values or multiple actions
- VOTE_RESULT: One of: passed, failed, tabled, unanimous (or empty if not voted). Do NOT use vote details here.
- VOTE_DETAILS: Plain text like "5 yes, 2 no, 1 abstain" (or empty if not voted). Do NOT use JSON.
- EXCERPT: The relevant sentence (escape pipes with \\|)

Return each legislation as ONE line only. If no legislation found, return NONE

Examples:
ordinance|2025-139|3% Water Rate Increase|approved|passed|5 yes, 0 no, 0 abstain|Ordinance 2025-139 establishing a 3% water rate increase was approved unanimously.
resolution|2025-18|Approve Contract|introduced|||Resolution 2025-18 was introduced for approval.
ordinance|118-25|Amend Clothing Allowance|approved|passed|6 yes, 1 no|Ordinance 118-25 regarding council clothing allowance was approved.
motion|M-2025-5|Approve Minutes|approved|||The motion to approve minutes was approved by unanimous consent.
"""

        system_prompt = """You are extracting legislation mentions from government documents.
Return one legislation per line in this format: TYPE|NUMBER|TITLE|ACTION|VOTE_RESULT|VOTE_DETAILS|EXCERPT
Use \\| to escape pipes within excerpt text.
Return NONE if no legislation found.
No explanations, no other text."""

        response = await self._client.generate(prompt, system_prompt)
        
        if not response:
            return []
        
        legislation_list = []
        # Valid enum values for action
        valid_actions = {
            "introduced", "first_reading", "second_reading", "third_reading",
            "public_hearing", "amended", "tabled", "referred", "approved",
            "adopted", "failed", "vetoed", "withdrawn", "discussed"
        }
        
        try:
            lines = response.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line or line == "NONE" or line.startswith("No legislation"):
                    continue
                
                try:
                    # Parse pipe-delimited format
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) < 2:
                        continue
                    
                    # Unescape pipes in excerpt
                    if len(parts) >= 7:
                        parts[6] = parts[6].replace("\\|", "|")
                    
                    # Sanitize action: if it contains comma or slash, take first valid part
                    raw_action = (parts[3] if len(parts) > 3 else "discussed").lower().strip()
                    # Extract first valid action from comma or slash-separated values
                    action = "discussed"
                    for candidate in raw_action.replace("/", ",").split(","):
                        candidate = candidate.strip()
                        if candidate in valid_actions:
                            action = candidate
                            break
                    
                    legis = {
                        "type": parts[0].lower() if len(parts) > 0 else "motion",
                        "number": parts[1] if len(parts) > 1 else "",
                        "title": parts[2] if len(parts) > 2 and parts[2] != "N/A" else None,
                        "action": action,
                        "vote_result": parts[4] if len(parts) > 4 and parts[4] else None,
                        "vote_details": parts[5] if len(parts) > 5 and parts[5] else None,
                        "excerpt": parts[6] if len(parts) > 6 else None,
                    }
                    
                    # Validate required fields
                    if legis["type"] and legis["number"]:
                        legislation_list.append(legis)
                except Exception as parse_error:
                    logger.debug(f"Failed to parse legislation line '{line}': {parse_error}")
                    continue
            
            if legislation_list:
                logger.info(
                    f"Extracted {len(legislation_list)} legislation mentions from '{title}'"
                )
            return legislation_list
        
        except Exception as e:
            logger.warning(f"Legislation extraction error for '{title}': {e}")
            logger.debug(f"Raw response (first 500 chars): {response[:500]}")
            return []


    async def extract_meeting_metadata(
        self,
        title: str,
        document_type: Optional[str] = None,
        content_text: Optional[str] = None,
        local_path: Optional[str] = None,
        max_content_chars: int = 5000,
    ) -> Optional[dict]:
        """
        Extract meeting metadata (date, time, location) from agenda/minutes PDFs.
        
        Government meeting documents typically contain meeting details in headers
        or opening sections. This extracts that structured data.
        
        Args:
            title: Document title
            document_type: Type hint (agenda, minutes, etc.)
            content_text: Pre-extracted text content
            local_path: Path to local file for PDF extraction if no content
            max_content_chars: Maximum characters to send to AI
            
        Returns:
            Dict with extracted metadata or None on failure:
            {
                "meeting_date": "2025-01-15",  # ISO format
                "meeting_time": "19:00",  # 24-hour format
                "location": "Council Chambers, 123 Main St",
                "meeting_type": "Regular Meeting|Special Meeting|Work Session|etc",
                "confidence": "high|medium|low"
            }
        """
        if not self.enabled:
            logger.debug("AI not enabled - skipping meeting metadata extraction")
            return None
        
        # Only extract from meeting documents
        if not self._is_meeting_document(title, document_type):
            logger.debug(f"Document '{title}' is not a meeting document - skipping metadata extraction")
            return None
        
        # Get content for text-based documents
        content = content_text
        if not content and local_path:
            content = await extract_pdf_text(local_path, max_pages=3)  # Meeting info is usually at the top
        
        if not content:
            logger.debug(f"No content available for metadata extraction from '{title}'")
            return None
        
        # Truncate content - meeting info is usually in first few pages
        content = content[:max_content_chars]
        
        prompt = f"""Extract meeting metadata from this government document.

Document Title: {title}
Document Type: {document_type or 'unknown'}

DOCUMENT CONTENT:
{content}

---
Extract the EXACT meeting details if present. Look for:
1. Meeting date (e.g., "December 9, 2024", "12/9/2024")
2. Meeting time (e.g., "7:00 PM", "6:30 p.m.")
3. Location/venue (e.g., "Council Chambers", "City Hall, 123 Main St")
4. Meeting type (Regular Meeting, Special Meeting, Work Session, Public Hearing, etc.)

Respond with ONLY valid JSON (no markdown code blocks):
{{"meeting_date": "YYYY-MM-DD or null", "meeting_time": "HH:MM (24-hour) or null", "location": "full location string or null", "meeting_type": "type or null", "confidence": "high|medium|low"}}

IMPORTANT:
- Convert dates to ISO format (YYYY-MM-DD)
- Convert times to 24-hour format (e.g., 19:00 for 7:00 PM)
- If a field is not found, use null (not empty string)
- "high" confidence = exact date/time clearly stated
- "medium" confidence = inferred from context
- "low" confidence = guessed from title or partial info"""

        system_prompt = """You are extracting meeting metadata from government documents.
Return valid JSON only, no explanations.
Be precise with dates and times - convert to standard formats.
Only return data that is explicitly stated in the document."""

        response = await self._client.generate(prompt, system_prompt)
        
        if not response:
            logger.debug(f"No AI response for metadata extraction from '{title}'")
            return None
        
        try:
            # Clean up response
            response_text = response.strip()
            if response_text.startswith("```"):
                parts = response_text.split("```")
                if len(parts) >= 2:
                    response_text = parts[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:].lstrip()
            
            result = json.loads(response_text)
            
            # Validate and normalize the response
            metadata = {
                "meeting_date": result.get("meeting_date"),
                "meeting_time": result.get("meeting_time"),
                "location": result.get("location"),
                "meeting_type": result.get("meeting_type"),
                "confidence": result.get("confidence", "low"),
            }
            
            # Validate date format
            if metadata["meeting_date"]:
                try:
                    datetime.strptime(metadata["meeting_date"], "%Y-%m-%d")
                except ValueError:
                    logger.warning(f"Invalid date format '{metadata['meeting_date']}' from '{title}'")
                    metadata["meeting_date"] = None
            
            # Validate time format
            if metadata["meeting_time"]:
                try:
                    datetime.strptime(metadata["meeting_time"], "%H:%M")
                except ValueError:
                    logger.warning(f"Invalid time format '{metadata['meeting_time']}' from '{title}'")
                    metadata["meeting_time"] = None
            
            # Check if we got any useful data
            if not any([metadata["meeting_date"], metadata["meeting_time"], metadata["location"]]):
                logger.debug(f"No useful metadata extracted from '{title}'")
                return None
            
            logger.info(
                f"Extracted meeting metadata from '{title}': "
                f"date={metadata['meeting_date']}, time={metadata['meeting_time']}, "
                f"location={metadata['location'][:50] + '...' if metadata['location'] and len(metadata['location']) > 50 else metadata['location']}"
            )
            
            return metadata
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse meeting metadata JSON from '{title}': {e}")
            logger.debug(f"Raw response: {response[:500]}")
            return None
    
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

    async def validate_metadata(
        self,
        title: str,
        current_document_type: Optional[str],
        content_text: Optional[str] = None,
        local_path: Optional[str] = None,
        max_content_chars: int = 3000,
    ) -> Optional[dict]:
        """
        Validate and potentially correct document metadata using AI.
        
        Args:
            title: Document title
            current_document_type: Current document type from scraper
            content_text: Pre-extracted text content
            local_path: Path to local file for PDF extraction if no content
            max_content_chars: Maximum characters to send to AI
            
        Returns:
            Dict with validated metadata or None on failure:
            {
                "document_type": "agenda|minutes|video|ordinance|resolution|packet|other",
                "document_type_confidence": "high|medium|low",
                "document_type_reason": "Brief explanation if changed"
            }
        """
        if not self.enabled:
            return None
        
        # Get content
        content = content_text
        if not content and local_path:
            content = await extract_pdf_text(local_path, max_pages=3)
        
        if not content:
            return None
        
        content = content[:max_content_chars]
        
        prompt = f"""Analyze this government document and validate its metadata.

Document Title: {title}
Current Type: {current_document_type or 'unknown'}

DOCUMENT CONTENT (first part):
{content}

---
Based on the ACTUAL CONTENT (not just the title), determine the correct document type.

Valid types:
- "agenda" = Future meeting agenda listing items to be discussed
- "minutes" = Official record of what happened at a past meeting (votes, motions, attendance)
- "packet" = Combined agenda + supporting documents
- "ordinance" = Local law or regulation
- "resolution" = Formal decision/statement (not a law)
- "video" = Video recording
- "other" = Doesn't fit above categories

Respond with ONLY valid JSON (no markdown):
{{"document_type": "<type>", "confidence": "high|medium|low", "reason": "brief explanation if type differs from current"}}"""

        system_prompt = "You are a document classifier for government records. Respond with valid JSON only."
        
        response = await self._client.generate(prompt, system_prompt)
        
        if not response:
            return None
        
        try:
            # Clean up response
            response_text = response.strip()
            if response_text.startswith("```"):
                parts = response_text.split("```")
                if len(parts) >= 2:
                    response_text = parts[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:].lstrip()
            
            result = json.loads(response_text)
            
            # Validate the response structure
            if "document_type" not in result:
                return None
            
            # Normalize document type
            valid_types = {"agenda", "minutes", "video", "ordinance", "resolution", "packet", "other"}
            doc_type = result.get("document_type", "").lower()
            if doc_type not in valid_types:
                doc_type = "other"
            
            validated = {
                "document_type": doc_type,
                "confidence": result.get("confidence", "medium"),
                "reason": result.get("reason", "")
            }
            
            # Log if type changed
            if current_document_type and doc_type != current_document_type:
                logger.info(
                    f"Metadata validation suggests type change for '{title}': "
                    f"{current_document_type} -> {doc_type} ({validated['confidence']} confidence: {validated['reason']})"
                )
            
            return validated
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse metadata validation JSON: {e}")
            return None



