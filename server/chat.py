"""
Civic Commons Chat Service

Provides conversational AI access to civic data using Gemini with function calling.
"""

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, AsyncIterator, Optional

import httpx

from config import get_city_config
from db import Database

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


# Tool definitions for Gemini function calling
TOOL_DEFINITIONS = {
    "get_events": {
        "name": "get_events",
        "description": "Search for upcoming or past events and meetings. Use this to find city council meetings, school board meetings, commission meetings, library events, and community events.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date for search in YYYY-MM-DD format. Defaults to today."
                },
                "end_date": {
                    "type": "string",
                    "description": "End date for search in YYYY-MM-DD format. Defaults to 30 days from start."
                },
                "source_name": {
                    "type": "string",
                    "description": "Filter by source name (partial match). Examples: 'Library', 'City Council', 'School', 'Parks', 'Rotary'. Leave empty to search all sources."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of events to return. Default 20."
                }
            },
            "required": []
        }
    },
    "search_documents": {
        "name": "search_documents",
        "description": "Search meeting minutes, agendas, and other civic documents by keyword or topic. Returns documents matching the search query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find relevant documents. Can be keywords, topics, or natural language."
                },
                "source_type": {
                    "type": "string",
                    "description": "Filter by source type: city_council, school_board, etc."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results. Default 10."
                }
            },
            "required": ["query"]
        }
    },
    "get_document_content": {
        "name": "get_document_content",
        "description": "Get the full content of a specific document by ID. Use this after searching to read document details.",
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "integer",
                    "description": "The document ID to retrieve content for."
                }
            },
            "required": ["document_id"]
        }
    },
    "find_legislation": {
        "name": "find_legislation",
        "description": "Search for legislation mentions (ordinances, resolutions, motions) and their status across meetings.",
        "parameters": {
            "type": "object",
            "properties": {
                "legislation_type": {
                    "type": "string",
                    "description": "Type of legislation: ordinance, resolution, motion, proclamation"
                },
                "legislation_number": {
                    "type": "string",
                    "description": "Specific legislation number to search for (e.g., '2025-01', 'R-2025-12')"
                },
                "search_text": {
                    "type": "string",
                    "description": "Text to search in legislation titles"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results. Default 20."
                }
            },
            "required": []
        }
    }
}


class ChatService:
    """
    Chat service using Gemini with function calling for civic data access.
    """
    
    GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    GEMINI_STREAM_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent"
    
    def __init__(self, db: Database, api_key: Optional[str] = None):
        """
        Initialize chat service.
        
        Args:
            db: Database instance for tool execution
            api_key: Gemini API key. If None, reads from environment.
        """
        self.db = db
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
        """Build Gemini tools configuration."""
        return [{
            "function_declarations": list(TOOL_DEFINITIONS.values())
        }]
    
    async def _execute_tool(self, name: str, args: dict) -> dict[str, Any]:
        """
        Execute a tool call and return the result.
        
        Args:
            name: Tool name
            args: Tool arguments
            
        Returns:
            Tool execution result
        """
        logger.info(f"Executing tool: {name} with args: {args}")
        
        try:
            if name == "get_events":
                return await self._tool_get_events(args)
            elif name == "search_documents":
                return await self._tool_search_documents(args)
            elif name == "get_document_content":
                return await self._tool_get_document_content(args)
            elif name == "find_legislation":
                return await self._tool_find_legislation(args)
            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {"error": str(e)}
    
    async def _tool_get_events(self, args: dict) -> dict[str, Any]:
        """Execute get_events tool."""
        today = date.today()
        
        start_str = args.get("start_date")
        end_str = args.get("end_date")
        source_name = args.get("source_name")  # Changed from source_type
        limit = args.get("limit", 20)
        
        start = date.fromisoformat(start_str) if start_str else today
        end = date.fromisoformat(end_str) if end_str else start + timedelta(days=30)
        
        events = await self.db.get_events(
            city_id=self.city_id,
            start_date=start,
            end_date=end,
            source_name=source_name,  # Changed from source_type
            limit=limit,
        )
        
        return {
            "date_range": {"start": start.isoformat(), "end": end.isoformat()},
            "total": len(events),
            "events": [
                {
                    "id": e["id"],
                    "title": e["title"],
                    "description": e.get("description"),
                    "start_time": e["start_time"].isoformat() if e.get("start_time") else None,
                    "location": e.get("location"),
                    "source": e.get("source_name"),
                    "source_url": e.get("source_url"),
                }
                for e in events
            ]
        }
    
    async def _tool_search_documents(self, args: dict) -> dict[str, Any]:
        """Execute search_documents tool."""
        query = args.get("query", "")
        source_type = args.get("source_type")
        limit = args.get("limit", 10)
        
        results = await self.db.search_documents(
            city_id=self.city_id,
            query=query,
            source_type=source_type,
            limit=limit,
        )
        
        return {
            "query": query,
            "total": len(results),
            "documents": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "type": r.get("document_type"),
                    "published_date": r["published_date"].isoformat() if r.get("published_date") else None,
                    "source": r.get("source_name"),
                    "source_url": r.get("source_url"),
                    "relevance": float(r.get("rank", 0)),
                }
                for r in results
            ]
        }
    
    async def _tool_get_document_content(self, args: dict) -> dict[str, Any]:
        """Execute get_document_content tool."""
        doc_id = args.get("document_id")
        if not doc_id:
            return {"error": "document_id is required"}
        
        doc = await self.db.get_document_content(doc_id)
        if not doc:
            return {"error": f"Document {doc_id} not found"}
        
        # Return markdown content if available, otherwise plain text
        content = doc.get("content_markdown") or doc.get("content_text")
        
        # Truncate very long content
        max_length = 8000
        if content and len(content) > max_length:
            content = content[:max_length] + "\n\n... [content truncated]"
        
        return {
            "id": doc["id"],
            "title": doc["title"],
            "type": doc.get("document_type"),
            "content": content,
            "source": doc.get("source_name"),
        }
    
    async def _tool_find_legislation(self, args: dict) -> dict[str, Any]:
        """Execute find_legislation tool."""
        leg_type = args.get("legislation_type")
        leg_number = args.get("legislation_number")
        search_text = args.get("search_text")
        limit = args.get("limit", 20)
        
        # Build query for legislation_mentions table
        query = """
            SELECT 
                lm.id,
                lm.legislation_type,
                lm.legislation_number,
                lm.legislation_title,
                lm.action_taken,
                lm.vote_result,
                lm.vote_details,
                lm.mentioned_date,
                d.title as document_title,
                e.title as event_title,
                e.start_time as event_date
            FROM legislation_mentions lm
            LEFT JOIN documents d ON lm.document_id = d.id
            LEFT JOIN events e ON lm.event_id = e.id
            WHERE 1=1
        """
        params: list[Any] = []
        
        if leg_type:
            params.append(leg_type)
            query += f" AND lm.legislation_type = ${len(params)}"
        
        if leg_number:
            params.append(f"%{leg_number}%")
            query += f" AND lm.legislation_number ILIKE ${len(params)}"
        
        if search_text:
            params.append(f"%{search_text}%")
            query += f" AND lm.legislation_title ILIKE ${len(params)}"
        
        query += " ORDER BY lm.mentioned_date DESC NULLS LAST, lm.id DESC"
        params.append(limit)
        query += f" LIMIT ${len(params)}"
        
        async with self.db.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        return {
            "total": len(rows),
            "legislation": [
                {
                    "type": r["legislation_type"],
                    "number": r["legislation_number"],
                    "title": r["legislation_title"],
                    "action": r["action_taken"],
                    "vote_result": r["vote_result"],
                    "vote_details": dict(r["vote_details"]) if r["vote_details"] else None,
                    "document": r["document_title"],
                    "event": r["event_title"],
                    "date": r["event_date"].isoformat() if r["event_date"] else None,
                }
                for r in rows
            ]
        }
    
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
