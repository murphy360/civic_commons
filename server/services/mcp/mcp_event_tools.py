"""
MCP tool registration for event operations.

Exposes event_tools module functions as MCP tools that the scraper can call.
Provides decision-making (not database write) capabilities via JSON-RPC.
"""

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .event_tools import analyze_event_for_upsert


def register_event_tools(
    mcp: FastMCP, 
    db: Any, 
    ai_processor: Optional[Any] = None,
    activity_logger: Optional[Any] = None,
) -> None:
    """
    Register event analysis tools with MCP server.

    These tools provide decision-making for scraper about event creation/merging.
    They do NOT perform database writes - scraper implements decisions.

    Args:
        mcp: FastMCP server instance
        db: Server Database instance (read-only access)
        ai_processor: Optional AIEventProcessor for dedup verification
        activity_logger: Optional ActivityLogger for logging tool calls
    """

    @mcp.tool()
    async def analyze_event_for_upsert_tool(
        source_id: int,
        title: str,
        start_time: str,
        location: Optional[str] = None,
        description: Optional[str] = None,
        end_time: Optional[str] = None,
        category: Optional[str] = None,
        is_virtual: bool = False,
        virtual_url: Optional[str] = None,
        external_id: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Analyze an event and recommend action for scraper to implement.

        This tool does NOT create or merge events in the database.
        It makes intelligent recommendations based on:
        - Exact external_id matching
        - Title/date similarity analysis
        - AI-powered duplicate verification (if available)

        The scraper is responsible for implementing the recommendation.

        Args:
            source_id: Event source ID
            title: Event title (required)
            start_time: ISO format datetime (e.g., "2024-01-15T19:00:00")
            location: Event location
            description: Event description
            end_time: ISO format datetime
            category: Event category
            is_virtual: Virtual event flag
            virtual_url: Virtual event URL
            external_id: External source unique ID
            source_url: Source website URL

        Returns:
            {
                "action": "create" | "merge" | "error",
                "event_id": int | null (if merge),
                "confidence": float | null (if merge, 0.0-1.0),
                "reasoning": str,
                "error": str | null (if error)
            }

        Example response for creation:
            {
                "action": "create",
                "event_id": null,
                "confidence": null,
                "reasoning": "No similar events found",
                "error": null
            }

        Example response for merge:
            {
                "action": "merge",
                "event_id": 42,
                "confidence": 0.95,
                "reasoning": "Exact external_id match",
                "error": null
            }
        """
        return await analyze_event_for_upsert(
            db=db,
            ai_processor=ai_processor,
            source_id=source_id,
            title=title,
            start_time=start_time,
            location=location,
            description=description,
            end_time=end_time,
            category=category,
            is_virtual=is_virtual,
            virtual_url=virtual_url,
            external_id=external_id,
            source_url=source_url,
            activity_logger=activity_logger,
        )



