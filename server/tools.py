"""
Civic Commons MCP Server - Tool Definitions

Defines the MCP tools exposed to LLM clients.
"""

from datetime import date, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from db import Database


def register_tools(mcp: FastMCP, db: Database) -> None:
    """
    Register all MCP tools with the server.
    
    Args:
        mcp: The FastMCP server instance
        db: The database instance
    """
    
    @mcp.tool()
    async def get_commons_calendar(
        city_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Get community events within a date range.
        
        Use this tool to find upcoming meetings, events, and activities
        in a community. Great for questions like "What's happening this week?"
        or "When is the next city council meeting?"
        
        Args:
            city_id: The city identifier (e.g., "twinsburg")
            start_date: Start date in YYYY-MM-DD format (defaults to today)
            end_date: End date in YYYY-MM-DD format (defaults to 30 days out)
            source_type: Filter by source type (e.g., "city_council", "library")
            limit: Maximum number of events to return (default 50)
            
        Returns:
            Dictionary containing events list and metadata
        """
        # Parse dates with defaults
        today = date.today()
        
        if start_date:
            start = date.fromisoformat(start_date)
        else:
            start = today
        
        if end_date:
            end = date.fromisoformat(end_date)
        else:
            end = today + timedelta(days=30)
        
        # Fetch events
        events = await db.get_events(
            city_id=city_id,
            start_date=start,
            end_date=end,
            source_type=source_type,
            limit=limit,
        )
        
        # Format response
        return {
            "city_id": city_id,
            "date_range": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "total_count": len(events),
            "events": [
                {
                    "title": e["title"],
                    "description": e.get("description"),
                    "start_time": e["start_time"].isoformat() if e.get("start_time") else None,
                    "end_time": e["end_time"].isoformat() if e.get("end_time") else None,
                    "location": e.get("location"),
                    "source": e.get("source_name"),
                    "source_url": e.get("source_url"),
                }
                for e in events
            ],
        }
    
    @mcp.tool()
    async def search_commons_records(
        city_id: str,
        query: str,
        source_type: str | None = None,
        include_content: bool = False,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Search community documents and records.
        
        Use this tool to find meeting minutes, agendas, ordinances,
        and other official documents. Great for questions like
        "What did the council decide about the new park?" or
        "Find documents about zoning changes."
        
        Args:
            city_id: The city identifier (e.g., "twinsburg")
            query: Search query (supports natural language)
            source_type: Filter by source type (e.g., "city_council", "school_board")
            include_content: Whether to include full document content
            limit: Maximum number of results (default 10)
            
        Returns:
            Dictionary containing search results and metadata
        """
        # Search documents
        results = await db.search_documents(
            city_id=city_id,
            query=query,
            source_type=source_type,
            limit=limit,
        )
        
        # Optionally fetch full content for top results
        documents = []
        for r in results:
            doc = {
                "id": r["id"],
                "title": r["title"],
                "document_type": r.get("document_type"),
                "published_date": r["published_date"].isoformat() if r.get("published_date") else None,
                "source": r.get("source_name"),
                "source_url": r.get("source_url"),
                "relevance_score": float(r.get("rank", 0)),
            }
            
            if include_content:
                full_doc = await db.get_document_content(r["id"])
                if full_doc:
                    # Prefer markdown, fall back to plain text
                    doc["content"] = full_doc.get("content_markdown") or full_doc.get("content_text")
            
            documents.append(doc)
        
        return {
            "city_id": city_id,
            "query": query,
            "total_count": len(documents),
            "documents": documents,
        }
    
    @mcp.tool()
    async def get_assistant_manifest(
        city_id: str,
    ) -> dict[str, Any]:
        """
        Get the assistant configuration for a community.
        
        Use this tool at the start of a conversation to get the
        assistant's name, persona, and community context.
        
        Args:
            city_id: The city identifier (e.g., "twinsburg")
            
        Returns:
            Dictionary containing assistant name, persona, and city info
        """
        config = await db.get_assistant_config(city_id)
        
        if not config:
            return {
                "error": f"City '{city_id}' not found",
                "available_cities": [],  # TODO: Query available cities
            }
        
        return {
            "city_id": config["city_id"],
            "display_name": config.get("display_name"),
            "assistant": {
                "name": config.get("assistant_name", "Commons Assistant"),
                "persona": config.get("assistant_persona"),
            },
            "timezone": config.get("timezone", "America/New_York"),
            "metadata": config.get("metadata", {}),
        }
    
    @mcp.tool()
    async def get_source_health(
        city_id: str,
    ) -> dict[str, Any]:
        """
        Get the health status of data sources.
        
        Use this tool to check if data sources are working correctly.
        Helpful for understanding data freshness and availability.
        
        Args:
            city_id: The city identifier (e.g., "twinsburg")
            
        Returns:
            Dictionary containing source health information
        """
        sources = await db.get_source_health(city_id)
        
        # Calculate summary
        healthy = sum(1 for s in sources if s.get("health_status") == "healthy")
        degraded = sum(1 for s in sources if s.get("health_status") == "degraded")
        unhealthy = sum(1 for s in sources if s.get("health_status") == "unhealthy")
        
        return {
            "city_id": city_id,
            "summary": {
                "total": len(sources),
                "healthy": healthy,
                "degraded": degraded,
                "unhealthy": unhealthy,
            },
            "sources": [
                {
                    "name": s["name"],
                    "type": s["source_type"],
                    "status": s.get("health_status", "unknown"),
                    "last_success": s["last_success_at"].isoformat() if s.get("last_success_at") else None,
                    "last_error": s.get("last_error"),
                    "is_enabled": s.get("is_enabled", True),
                }
                for s in sources
            ],
        }
