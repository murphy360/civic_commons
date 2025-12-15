"""
Gemini API client for AI-powered event processing.

This module provides a reusable HTTP client for calling Google's Gemini API.
It handles authentication, request formatting, and response parsing.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("civic.ai.client")


class GeminiClient:
    """
    HTTP client for Gemini API.
    
    Handles connection management, authentication, and request/response formatting.
    """
    
    # Use gemini-2.0-flash which is available in the API
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    
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
        max_tokens: int = 1024,
    ) -> Optional[str]:
        """
        Call Gemini API with a prompt.
        
        Args:
            prompt: The user prompt to send
            system_prompt: Optional system instructions
            temperature: Sampling temperature (0.0-1.0, lower = more deterministic)
            max_tokens: Maximum tokens in response
        
        Returns:
            Generated text response or None on error
        """
        if not self.api_key:
            return None
        
        client = await self._get_client()
        
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
        
        try:
            response = await client.post(
                f"{self.GEMINI_API_URL}?key={self.api_key}",
                json={
                    "contents": contents,
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                    }
                }
            )
            response.raise_for_status()
            
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API HTTP error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
    
    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> Optional[dict]:
        """
        Call Gemini API and parse response as JSON.
        
        Convenience method that handles JSON extraction from the response,
        including stripping markdown code blocks if present.
        
        Args:
            prompt: The user prompt to send
            system_prompt: Optional system instructions (should request JSON output)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            
        Returns:
            Parsed JSON as dict, or None on error
        """
        import json
        
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
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
