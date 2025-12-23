"""
Gemini API client for AI-powered event processing.

This module provides a reusable HTTP client for calling Google's Gemini API.
It handles authentication, request formatting, and response parsing.

Model Usage:
- gemini-2.5-flash: Document summaries, event summaries (fast, cost-effective, improved reasoning)
- gemini-2.5-flash: Video analysis, weekly/monthly summaries (balanced)
- gemini-2.5-pro: Complex reasoning, quarterly/annual summaries (deep thinking)
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("civic.ai.client")


# Gemini API base URL
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Model endpoints
MODELS = {
    # Fast model for basic document/event summaries
    "flash": f"{GEMINI_API_BASE}/gemini-2.5-flash:generateContent",
    
    # Balanced model for video analysis and weekly/monthly summaries  
    "flash-2.5": f"{GEMINI_API_BASE}/gemini-2.5-flash:generateContent",
    
    # Advanced thinking model for complex quarterly summaries
    "pro": f"{GEMINI_API_BASE}/gemini-2.5-pro:generateContent",
    
    # Gemini 3 Pro Preview for annual summaries (most comprehensive)
    "pro-3": f"{GEMINI_API_BASE}/gemini-3-pro-preview:generateContent",
    
    # Chat agent model (Gemini 3 Pro preview)
    "chat": f"{GEMINI_API_BASE}/gemini-3-pro-preview:generateContent",
}


class GeminiClient:
    """
    HTTP client for Gemini API.
    
    Handles connection management, authentication, and request/response formatting.
    Supports multiple models for different use cases.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Gemini client.
        
        Args:
            api_key: API key for Gemini. If None, reads from environment.
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
        
        if not self.api_key:
            logger.warning("No Gemini API key configured - AI processing disabled")
        
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def enabled(self) -> bool:
        """Check if the client is enabled (has API key)."""
        return bool(self.api_key)
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def generate(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        model: str = "flash",
    ) -> Optional[str]:
        """
        Call Gemini API with a prompt.
        
        Args:
            prompt: The user prompt to send
            system_prompt: Optional system instructions
            temperature: Sampling temperature (0.0-1.0, lower = more deterministic)
            max_tokens: Maximum tokens in response (None = use model default)
            model: Model to use - "flash" (2.0), "flash-2.5", or "pro" (2.5)
        
        Returns:
            Generated text response or None on error
        """
        if not self.api_key:
            return None
        
        # Get the model URL
        model_url = MODELS.get(model, MODELS["flash"])
        
        # Use longer timeout for pro model
        timeout = 120.0 if model == "pro" else 60.0
        client = httpx.AsyncClient(timeout=timeout)
        
        # Build the request contents
        contents = []
        if system_prompt:
            contents.append({
                "role": "user",
                "parts": [{"text": system_prompt}]
            })
            contents.append({
                "role": "model", 
                "parts": [{"text": "I understand. I'll follow these instructions."}]
            })
        
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })
        
        # Build generation config - only include maxOutputTokens if explicitly set
        generation_config = {"temperature": temperature}
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        
        try:
            logger.debug(f"Using model: {model} -> {model_url}")
            response = await client.post(
                f"{model_url}?key={self.api_key}",
                json={
                    "contents": contents,
                    "generationConfig": generation_config
                }
            )
            await client.aclose()
            response.raise_for_status()
            
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API HTTP error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
    
    async def generate_with_video(
        self,
        prompt: str,
        video_url: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """
        Call Gemini API with a YouTube video URL for analysis.
        
        Uses Gemini 2.5 Flash for video analysis capability.
        
        Args:
            prompt: The user prompt to send
            video_url: YouTube video URL to analyze
            system_prompt: Optional system instructions
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response (None = use model default)
        
        Returns:
            Generated text response or None on error
        """
        if not self.api_key:
            return None
        
        # Use flash-2.5 model for video analysis
        model_url = MODELS["flash-2.5"]
        
        # Build the request contents with video
        contents = []
        if system_prompt:
            contents.append({
                "role": "user",
                "parts": [{"text": system_prompt}]
            })
            contents.append({
                "role": "model", 
                "parts": [{"text": "I understand. I'll follow these instructions."}]
            })
        
        # Include video URL and prompt together
        contents.append({
            "role": "user",
            "parts": [
                {
                    "fileData": {
                        "mimeType": "video/youtube",
                        "fileUri": video_url
                    }
                },
                {"text": prompt}
            ]
        })
        
        # Build generation config - only include maxOutputTokens if explicitly set
        generation_config = {"temperature": temperature}
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        
        try:
            client = httpx.AsyncClient(timeout=120.0)  # Videos may take longer
            response = await client.post(
                f"{model_url}?key={self.api_key}",
                json={
                    "contents": contents,
                    "generationConfig": generation_config
                }
            )
            await client.aclose()
            response.raise_for_status()
            
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API HTTP error (video): {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Gemini API error (video): {e}")
            return None

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
        model: str = "flash",
    ) -> Optional[dict]:
        """
        Call Gemini API and parse response as JSON.
        
        Convenience method that handles JSON extraction from the response,
        including stripping markdown code blocks if present.
        
        Args:
            prompt: The user prompt to send
            system_prompt: Optional system instructions (should request JSON output)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response (None = use model default)
            model: Model to use - "flash" (2.0), "flash-2.5", or "pro" (2.5)
            
        Returns:
            Parsed JSON as dict, or None on error
        """
        import json
        
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )
        
        if not response:
            return None
        
        try:
            # Strip markdown code blocks if present
            text = response.strip()
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            
            return json.loads(text.strip())
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {response}")
            return None


# Singleton instance for reuse
_client: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    """Get or create the singleton Gemini client instance."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
