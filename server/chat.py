"""
Civic Commons Chat Service

Provides conversational AI access to civic data using Gemini with function calling.
Uses read-only tools from the unified tool registry - write operations are restricted.
"""

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, AsyncIterator, Optional

import httpx

from config import get_city_config
from db import Database
from tool_registry import get_tools_for_gemini
from tool_executor import ToolExecutor

logger = logging.getLogger("civic_commons.chat")


def get_system_prompt(assistant_name: str = "Assistant", city_name: str = "your community") -> str:
    """Generate system prompt with current date/time and configured assistant identity."""
    now = datetime.now()
    today = now.strftime("%A, %B %d, %Y")
    current_time = now.strftime("%I:%M %p")
    
    return f"""You are {assistant_name}, a friendly and helpful AI assistant for the Civic Commons platform in {city_name}.

CURRENT DATE AND TIME: {today} at {current_time}

Your role is to help residents find information about:
- Upcoming meetings and events (city council, school board, commissions, etc.)
- Meeting minutes, agendas, and civic documents  
- Legislation (ordinances, resolutions) and their status
- General information about local government

IMPORTANT GUIDELINES:

1. BE PROACTIVE - DON'T ASK UNNECESSARY QUESTIONS
   - When someone asks about meetings, SEARCH FIRST and show results
   - Don't ask "what type of meeting?" - just search and show what you find
   - Let users explore by showing results, then offer to filter/refine
   
2. SHOW RESULTS, THEN OFFER OPTIONS
   - Example: "Here are 12 meetings coming up this week. Here are the next 5:
     [list 5 meetings]
     Would you like to see more, or focus on a specific type (City Council, School Board, etc.)?"
   
3. USE SENSIBLE DEFAULTS
   - "upcoming meetings" = next 14 days from today ({now.strftime("%Y-%m-%d")})
   - "recent" = last 30 days
   - "this week" = next 7 days
   - If no date specified, assume they want upcoming events
   
4. BE CONVERSATIONAL AND HELPFUL
   - Provide specific dates, times, and locations
   - Format with markdown for readability
   - Cite sources (which document or meeting the info came from)
   
5. WHEN SHOWING MANY RESULTS
   - Show 5-7 most relevant items first
   - Mention how many more exist
   - Offer to show more or filter

Remember: Your job is to help people discover civic information easily. Don't make them work to get answers - search first, show results, then help them refine if needed.
"""


def get_gemini_tools_config(city_id: str) -> list[dict]:
    """
    Get tool definitions for Gemini function calling (read-only tools only).
    
    Args:
        city_id: City context
        
    Returns:
        List of tool definitions in Gemini format
    """
    tools = get_tools_for_gemini(city_id)
    return [{"function_declarations": list(tools.values())}]


class ChatService:
    """
    Chat service using Gemini with function calling for civic data access.
    """
    
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    GEMINI_STREAM_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent"
    
    def __init__(self, db: Database, executor: Optional[ToolExecutor] = None, api_key: Optional[str] = None):
        """
        Initialize chat service.
        
        Args:
            db: Database instance for tool execution
            executor: ToolExecutor instance. If None, creates a new one.
            api_key: Gemini API key. If None, reads from environment.
        """
        self.db = db
        self.executor = executor or ToolExecutor()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
        self._client: Optional[httpx.AsyncClient] = None
        
        # Load city config for assistant identity
        city_config = get_city_config()
        self.city_id = city_config.get("city_profile", {}).get("name", "community").lower().replace(" ", "_").replace(",", "")
        self.city_name = city_config.get("city_profile", {}).get("name", "your community")
        self.assistant_name = city_config.get("assistant", {}).get("name", "Assistant")
        self.assistant_persona = city_config.get("assistant", {}).get("persona", "")
        
        if not self.api_key:
            logger.warning("No Gemini API key configured - chat disabled")
    
    @property
    def enabled(self) -> bool:
        """Check if chat service is enabled."""
        return bool(self.api_key)
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _build_tools_config(self) -> list[dict]:
        """
        Build Gemini tools configuration from unified registry.
        Only includes read-only tools for Gemini safety.
        """
        return get_gemini_tools_config(self.city_id)
    
    async def _execute_tool(self, name: str, args: dict) -> dict[str, Any]:
        """
        Execute a tool call through the unified executor.
        
        Args:
            name: Tool name
            args: Tool arguments
            
        Returns:
            Tool execution result
        """
        logger.info(f"Executing tool via chat: {name}")
        
        result = await self.executor.execute_tool(
            name=name,
            args=args,
            source="chat",
            city_id=self.city_id,
            access_level="read_only",
        )
        
        if result.success:
            return result.result
        else:
            return {"error": result.error}
    
    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Process a chat message with function calling.
        
        Args:
            messages: List of messages with 'role' and 'content'
            stream: Whether to stream the response
            
        Yields:
            Response chunks with type, content, and optional tool calls
        """
        if not self.enabled:
            yield {
                "type": "error",
                "content": "Chat service is not configured. Please set GEMINI_API_KEY."
            }
            return
        
        client = await self._get_client()
        
        # Build Gemini conversation format
        contents = []
        
        # Add system prompt as first exchange (with current date/time and configured identity)
        system_prompt = get_system_prompt(self.assistant_name, self.city_name)
        contents.append({
            "role": "user",
            "parts": [{"text": system_prompt}]
        })
        contents.append({
            "role": "model",
            "parts": [{"text": f"Got it! I'm {self.assistant_name}, ready to help {self.city_name} residents explore civic information. I'll search first and show you what I find, then help you refine if needed. What would you like to know?"}]
        })
        
        # Add conversation messages
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
        
        # Make initial API call with tools
        try:
            response = await client.post(
                f"{self.GEMINI_API_URL}?key={self.api_key}",
                json={
                    "contents": contents,
                    "tools": self._build_tools_config(),
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 2048,
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Gemini API error: {e.response.status_code} - {e.response.text}")
            yield {
                "type": "error",
                "content": "Sorry, I encountered an error connecting to the AI service. Please try again."
            }
            return
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            yield {
                "type": "error",
                "content": "Sorry, I encountered an unexpected error. Please try again."
            }
            return
        
        # Process response - may need multiple rounds for function calling
        max_iterations = 5  # Prevent infinite loops
        
        for _ in range(max_iterations):
            candidate = data.get("candidates", [{}])[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            
            # Check for function calls
            function_calls = [p.get("functionCall") for p in parts if p.get("functionCall")]
            
            if function_calls:
                # Execute tool calls and report them
                tool_results = []
                
                for fc in function_calls:
                    tool_name = fc["name"]
                    tool_args = fc.get("args", {})
                    
                    # Yield tool call notification
                    yield {
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": tool_args,
                        "status": "pending"
                    }
                    
                    # Execute tool
                    result = await self._execute_tool(tool_name, tool_args)
                    
                    yield {
                        "type": "tool_call",
                        "tool": tool_name,
                        "args": tool_args,
                        "status": "complete",
                        "result_summary": f"Found {result.get('total', 0)} results" if 'total' in result else "Complete"
                    }
                    
                    tool_results.append({
                        "functionResponse": {
                            "name": tool_name,
                            "response": result
                        }
                    })
                
                # Add tool results to conversation and continue
                contents.append(content)  # Add model's function call
                contents.append({
                    "role": "user",
                    "parts": tool_results
                })
                
                # Make another API call with tool results
                try:
                    response = await client.post(
                        f"{self.GEMINI_API_URL}?key={self.api_key}",
                        json={
                            "contents": contents,
                            "tools": self._build_tools_config(),
                            "generationConfig": {
                                "temperature": 0.7,
                                "maxOutputTokens": 2048,
                            }
                        }
                    )
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    logger.error(f"Gemini API error in function loop: {e}")
                    yield {
                        "type": "error",
                        "content": "Sorry, I encountered an error processing the information. Please try again."
                    }
                    return
            else:
                # No function calls - extract text response
                text_parts = [p.get("text", "") for p in parts if p.get("text")]
                final_text = "\n".join(text_parts)
                
                yield {
                    "type": "message",
                    "content": final_text
                }
                return
        
        # If we exhausted iterations, return what we have
        yield {
            "type": "message",
            "content": "I apologize, but I'm having trouble processing your request. Please try rephrasing your question."
        }
