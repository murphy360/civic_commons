"""
Purpose: Driver for YouTube channel video scraping
Dependencies: httpx for HTTP, yt_dlp for YouTube metadata extraction
Consumed by: Worker for municipal YouTube channels
Side effects: HTTP requests to YouTube
"""

import re
from datetime import datetime, timedelta
from typing import Optional
import logging

import httpx

from .base import BaseDriver
from models import Event, Document
from models.document import DocumentType


logger = logging.getLogger("civic.driver")


class YouTubeChannelDriver(BaseDriver):
    """
    Driver for YouTube channel video feeds.
    
    Extracts videos from a YouTube channel and creates documents for each video.
    Videos are automatically linked to events based on date matching.
    
    Expected params in YAML config:
        channel_url: URL of the YouTube channel videos page
        max_videos: Maximum number of videos to fetch (default: 50)
        
    Example config:
        - name: "City YouTube Channel"
          driver: "youtube_channel"
          params:
            channel_url: "https://www.youtube.com/@CityofTwinsburg/videos"
            max_videos: 100
    """

    # Date patterns commonly found in government video titles
    DATE_PATTERNS = [
        # "January 28, 2025"
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
        # "Jan 28, 2025"
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}',
        # "1/28/2025" or "01/28/2025"
        r'\d{1,2}/\d{1,2}/\d{4}',
        # "2025-01-28"
        r'\d{4}-\d{2}-\d{2}',
        # "11/20" or "1/5" (short month/day - will assume current/recent year)
        r'\b\d{1,2}/\d{1,2}\b(?!/)',  # Negative lookahead to avoid matching part of m/d/yyyy
    ]

    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """Fetch videos from YouTube channel."""
        events: list[Event] = []
        documents: list[Document] = []

        channel_url = self.params.get("channel_url")
        if not channel_url:
            raise ValueError("Missing required param: channel_url")

        max_videos = self.params.get("max_videos", 50)
        
        self.log_info(f"Fetching YouTube channel: {channel_url}")

        try:
            videos = await self._fetch_channel_videos(channel_url, max_videos)
            
            for video in videos:
                doc = self._create_video_document(video)
                if doc:
                    documents.append(doc)

            self.log_info(f"Found {len(documents)} videos from YouTube channel")
            
        except Exception as e:
            self.log_error(f"Error fetching YouTube channel: {e}")
            raise

        return events, documents

    async def _fetch_channel_videos(self, channel_url: str, max_videos: int) -> list[dict]:
        """
        Fetch video list from YouTube channel.
        
        Uses the channel page HTML to extract video information.
        This avoids requiring yt-dlp as a dependency.
        """
        videos = []
        
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=60.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        ) as client:
            await self.rate_limit_delay()
            response = await client.get(channel_url)
            response.raise_for_status()
            
            html = response.text
            
            # Extract video data from the page's JavaScript
            # YouTube embeds video data in ytInitialData variable
            videos = self._parse_youtube_page(html, max_videos)
            
        return videos

    def _parse_youtube_page(self, html: str, max_videos: int) -> list[dict]:
        """
        Parse YouTube channel page HTML to extract video information.
        
        YouTube embeds video data in a JavaScript variable called ytInitialData.
        """
        import json
        
        videos = []
        
        # Find ytInitialData in the page
        match = re.search(r'var ytInitialData = ({.*?});', html, re.DOTALL)
        if not match:
            # Try alternate pattern
            match = re.search(r'ytInitialData\s*=\s*({.*?});', html, re.DOTALL)
        
        if not match:
            self.log_warning("Could not find ytInitialData in YouTube page")
            return videos
        
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as e:
            self.log_error(f"Failed to parse YouTube JSON: {e}")
            return videos
        
        # Navigate to video list in the data structure
        # Structure: contents > twoColumnBrowseResultsRenderer > tabs > tabRenderer > 
        #            content > richGridRenderer > contents > richItemRenderer > content > videoRenderer
        try:
            tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
            
            for tab in tabs:
                tab_content = tab.get("tabRenderer", {}).get("content", {})
                rich_grid = tab_content.get("richGridRenderer", {})
                contents = rich_grid.get("contents", [])
                
                for item in contents:
                    if len(videos) >= max_videos:
                        break
                        
                    rich_item = item.get("richItemRenderer", {})
                    video_renderer = rich_item.get("content", {}).get("videoRenderer", {})
                    
                    if video_renderer:
                        video_info = self._extract_video_info(video_renderer)
                        if video_info:
                            videos.append(video_info)
                            
        except Exception as e:
            self.log_error(f"Error navigating YouTube data structure: {e}")
        
        return videos

    def _extract_video_info(self, video_renderer: dict) -> Optional[dict]:
        """Extract video information from a videoRenderer object."""
        try:
            video_id = video_renderer.get("videoId")
            if not video_id:
                return None
            
            # Get title
            title_runs = video_renderer.get("title", {}).get("runs", [])
            title = title_runs[0].get("text", "") if title_runs else ""
            
            if not title:
                return None
            
            # Get description snippet
            description_runs = video_renderer.get("descriptionSnippet", {}).get("runs", [])
            description = "".join(run.get("text", "") for run in description_runs)
            
            # Get published time text (e.g., "2 weeks ago")
            published_text = video_renderer.get("publishedTimeText", {}).get("simpleText", "")
            
            # Get view count
            view_count_text = video_renderer.get("viewCountText", {}).get("simpleText", "")
            
            # Get length
            length_text = video_renderer.get("lengthText", {}).get("simpleText", "")
            
            # Construct video URL
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            return {
                "video_id": video_id,
                "title": title,
                "description": description,
                "url": video_url,
                "published_text": published_text,
                "published_date": self._parse_relative_date(published_text),
                "view_count": view_count_text,
                "length": length_text,
            }
            
        except Exception as e:
            self.log_debug(f"Error extracting video info: {e}")
            return None

    def _parse_relative_date(self, text: str) -> Optional[datetime]:
        """
        Parse relative date text like "2 weeks ago" to an actual datetime.
        
        Common patterns:
        - "X seconds ago"
        - "X minutes ago"
        - "X hours ago"
        - "X days ago"
        - "X weeks ago"
        - "X months ago"
        - "X years ago"
        - "Streamed X days ago"
        """
        if not text:
            return None
            
        text_lower = text.lower().strip()
        now = datetime.now()
        
        # Remove "Streamed " prefix if present
        text_lower = text_lower.replace("streamed ", "")
        
        # Parse the relative time
        patterns = [
            (r'(\d+)\s*second', 'seconds'),
            (r'(\d+)\s*minute', 'minutes'),
            (r'(\d+)\s*hour', 'hours'),
            (r'(\d+)\s*day', 'days'),
            (r'(\d+)\s*week', 'weeks'),
            (r'(\d+)\s*month', 'months'),
            (r'(\d+)\s*year', 'years'),
        ]
        
        for pattern, unit in patterns:
            match = re.search(pattern, text_lower)
            if match:
                value = int(match.group(1))
                if unit == 'seconds':
                    return now - timedelta(seconds=value)
                elif unit == 'minutes':
                    return now - timedelta(minutes=value)
                elif unit == 'hours':
                    return now - timedelta(hours=value)
                elif unit == 'days':
                    return now - timedelta(days=value)
                elif unit == 'weeks':
                    return now - timedelta(weeks=value)
                elif unit == 'months':
                    return now - timedelta(days=value * 30)  # Approximate
                elif unit == 'years':
                    return now - timedelta(days=value * 365)  # Approximate
        
        return None

    def _create_video_document(self, video: dict) -> Optional[Document]:
        """Create a Document from video info."""
        try:
            title = video.get("title", "")
            url = video.get("url", "")
            
            if not title or not url:
                return None
            
            # Try to extract date from title first
            meeting_date = self._extract_date_from_title(title)
            
            # Get published date from YouTube
            published_date = video.get("published_date")
            
            # If no meeting date in title, use published date as meeting date
            # This ensures videos without dates in titles can still be linked
            if not meeting_date and published_date:
                meeting_date = published_date
                self.log_debug(f"Using published date as meeting date for: {title}")
            
            # Clean up title - remove " - YouTube" suffix if present
            clean_title = re.sub(r'\s*-\s*YouTube\s*$', '', title).strip()
            
            # Append " - Video" if not already there
            if not clean_title.lower().endswith('video'):
                clean_title = f"{clean_title} - Video"
            
            doc = Document(
                title=clean_title,
                original_url=url,
                doc_type=DocumentType.VIDEO,
                meeting_date=meeting_date,
                published_at=published_date,
            )
            
            return doc
            
        except Exception as e:
            self.log_error(f"Error creating document from video: {e}")
            return None

    def _extract_date_from_title(self, title: str) -> Optional[datetime]:
        """
        Extract meeting date from video title.
        
        Government video titles usually include the meeting date:
        - "City of Twinsburg Council Meeting - January 28, 2025"
        - "Planning Commission Special Meeting - May 27, 2025"
        - "Board of Education Meeting 11/20" (short format)
        """
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, title)
            if match:
                date_str = match.group(0)
                try:
                    # Try different date formats
                    for fmt in [
                        "%B %d, %Y",      # January 28, 2025
                        "%B %d %Y",       # January 28 2025
                        "%b %d, %Y",      # Jan 28, 2025
                        "%b %d %Y",       # Jan 28 2025
                        "%m/%d/%Y",       # 1/28/2025
                        "%Y-%m-%d",       # 2025-01-28
                    ]:
                        try:
                            return datetime.strptime(date_str.replace(",", "").strip(), fmt.replace(",", ""))
                        except ValueError:
                            continue
                    
                    # Try short date format (m/d without year)
                    if re.match(r'^\d{1,2}/\d{1,2}$', date_str):
                        current_year = datetime.now().year
                        try:
                            # Try current year first
                            parsed = datetime.strptime(f"{date_str}/{current_year}", "%m/%d/%Y")
                            # If the date is more than 6 months in the future, assume last year
                            if (parsed - datetime.now()).days > 180:
                                parsed = datetime.strptime(f"{date_str}/{current_year - 1}", "%m/%d/%Y")
                            return parsed
                        except ValueError:
                            continue
                            
                except Exception:
                    pass
        
        return None
