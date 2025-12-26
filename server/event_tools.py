"""
Event deduplication decision logic for MCP.

Makes intelligent recommendations about event creation/merging via AI.
This tool does NOT perform database writes - it provides smart decisions
that the scraper's storage layer will implement.

Design principle:
- Read-only access to server Database
- Call AI for verification
- Return clear action recommendations
- Scraper implements the decision
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger("civic_commons.event_tools")


async def analyze_event_for_upsert(
    db: Any,
    ai_processor: Optional[Any],
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
    activity_logger: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Analyze an event and recommend an action for scraper to implement.

    This MCP tool does NOT perform database writes. It makes intelligent
    recommendations based on data analysis and AI verification.

    Decision path:
    1. Check exact external_id match (fast path, no AI needed)
    2. Search for similar events by title and date proximity
    3. If similar found, ask AI to verify duplication confidence
    4. Return recommendation: "create" or "merge_with_id_X"

    Args:
        db: Server Database instance (read-only)
        ai_processor: AIEventProcessor for intelligent verification
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
        activity_logger: Optional ActivityLogger for logging tool calls

    Returns:
        {
            "action": "create" | "merge" | "error",
            "event_id": int | null (if merge, ID to merge with),
            "confidence": float | null (if merge, 0.0-1.0),
            "reasoning": str,
            "error": str | null (if action is error)
        }

    Examples:
        >>> result = await analyze_event_for_upsert(db, ai_proc, 123, "Tech", "2024-01-15T19:00:00")
        >>> if result["action"] == "create":
        ...     # Scraper creates new event
        ... elif result["action"] == "merge":
        ...     # Scraper merges with result["event_id"]
    """
    start_time_ms = time.time() * 1000
    result = None
    
    try:
        # Parse start time
        start_dt = _parse_iso_datetime(start_time)

        # Fast path: check exact external_id match
        if external_id:
            match = await _check_external_id_match(db, source_id, external_id)
            if match:
                result = {
                    "action": "merge",
                    "event_id": match["id"],
                    "confidence": 1.0,
                    "reasoning": f"Exact external_id match: {external_id}",
                    "error": None,
                }
                # Log the decision
                if activity_logger:
                    duration_ms = time.time() * 1000 - start_time_ms
                    await activity_logger.log_tool_completed(
                        tool_name="analyze_event_for_upsert",
                        args={"title": title, "external_id": external_id},
                        result=result,
                        execution_time_ms=duration_ms,
                        source="mcp",
                    )
                return result

        # Search for similar events
        similar_events = await _find_similar_events(db, title, start_dt, location)

        if not similar_events:
            result = {
                "action": "create",
                "event_id": None,
                "confidence": None,
                "reasoning": "No similar events found",
                "error": None,
            }
            if activity_logger:
                duration_ms = time.time() * 1000 - start_time_ms
                await activity_logger.log_tool_completed(
                    tool_name="analyze_event_for_upsert",
                    args={"title": title},
                    result=result,
                    execution_time_ms=duration_ms,
                    source="mcp",
                )
            return result

        # If AI processor available, verify the best match
        best_match = similar_events[0]
        if ai_processor:
            verification = await _verify_with_ai(
                ai_processor, title, description, best_match
            )

            if verification["is_duplicate"]:
                result = {
                    "action": "merge",
                    "event_id": best_match["id"],
                    "confidence": verification["confidence"],
                    "reasoning": verification["reason"],
                    "error": None,
                }
                if activity_logger:
                    duration_ms = time.time() * 1000 - start_time_ms
                    await activity_logger.log_tool_completed(
                        tool_name="analyze_event_for_upsert",
                        args={"title": title},
                        result=result,
                        execution_time_ms=duration_ms,
                        source="mcp",
                    )
                return result

        result = {
            "action": "create",
            "event_id": None,
            "confidence": None,
            "reasoning": "Similar events found but AI did not confirm duplication",
            "error": None,
        }
        if activity_logger:
            duration_ms = time.time() * 1000 - start_time_ms
            await activity_logger.log_tool_completed(
                tool_name="analyze_event_for_upsert",
                args={"title": title},
                result=result,
                execution_time_ms=duration_ms,
                source="mcp",
            )
        return result

    except Exception as e:
        logger.exception("Error analyzing event for upsert")
        result = {
            "action": "error",
            "event_id": None,
            "confidence": None,
            "reasoning": None,
            "error": str(e),
        }
        if activity_logger:
            duration_ms = time.time() * 1000 - start_time_ms
            await activity_logger.log_tool_failed(
                tool_name="analyze_event_for_upsert",
                error=str(e),
                execution_time_ms=duration_ms,
                source="mcp",
            )
        return result


async def _check_external_id_match(
    db: Any, source_id: int, external_id: str
) -> Optional[dict[str, Any]]:
    """
    Check if event with exact external_id already exists.

    Args:
        db: Database instance
        source_id: Event source ID
        external_id: External unique ID from source

    Returns:
        Event dict if found, None otherwise
    """
    try:
        # Query for event with exact external_id
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT e.id, e.title, e.start_time
                FROM events e
                JOIN event_sources es ON e.id = es.event_id
                WHERE es.source_id = $1 AND es.external_id = $2
                LIMIT 1
                """,
                source_id,
                external_id,
            )
            return dict(row) if row else None
    except Exception as e:
        logger.warning(f"Error checking external_id match: {e}")
        return None


async def _find_similar_events(
    db: Any, title: str, start_dt: datetime, location: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Find events similar to the given event.

    Uses title similarity and date proximity (within 4 hours).

    Args:
        db: Database instance
        title: Event title to match
        start_dt: Event start datetime
        location: Optional location to filter by

    Returns:
        List of similar events, ordered by relevance
    """
    try:
        # Search window: 4 hours before/after
        window_start = start_dt - timedelta(hours=4)
        window_end = start_dt + timedelta(hours=4)

        async with db.pool.acquire() as conn:
            # Similarity search using trigram match
            query = """
                SELECT 
                    e.id, e.title, e.start_time, e.location, e.description,
                    similarity(e.title, $1) as title_sim
                FROM events e
                WHERE e.start_time BETWEEN $2 AND $3
                  AND similarity(e.title, $1) > 0.3
            """
            params: list[Any] = [title, window_start, window_end]

            if location:
                query += " AND e.location ILIKE $4"
                params.append(f"%{location}%")

            query += " ORDER BY title_sim DESC, e.start_time LIMIT 5"

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    except Exception as e:
        logger.warning(f"Error finding similar events: {e}")
        return []


async def _verify_with_ai(
    ai_processor: Any, title: str, description: Optional[str], similar_event: dict
) -> dict[str, Any]:
    """
    Use AI to verify if similar_event is a duplicate of the new event.

    Args:
        ai_processor: AIEventProcessor instance
        title: New event title
        description: New event description
        similar_event: Candidate existing event

    Returns:
        {
            "is_duplicate": bool,
            "confidence": float (0.0-1.0),
            "reason": str
        }
    """
    try:
        # Call AI processor to evaluate match
        result = await ai_processor.evaluate_event_match(
            new_title=title,
            new_description=description,
            existing_title=similar_event.get("title"),
            existing_description=similar_event.get("description"),
        )

        return {
            "is_duplicate": result.get("is_duplicate", False),
            "confidence": result.get("confidence", 0.0),
            "reason": result.get("reason", "AI evaluation"),
        }

    except Exception as e:
        logger.warning(f"Error verifying with AI: {e}")
        return {
            "is_duplicate": False,
            "confidence": 0.0,
            "reason": f"AI verification failed: {e}",
        }


def _parse_iso_datetime(iso_string: str) -> datetime:
    """
    Parse ISO datetime or date string.

    Args:
        iso_string: ISO format string (e.g., "2024-01-15" or "2024-01-15T19:00:00")

    Returns:
        datetime object
    """
    try:
        if "T" in iso_string:
            return datetime.fromisoformat(iso_string)
        else:
            # Date only - parse as midnight UTC
            return datetime.fromisoformat(iso_string + "T00:00:00")
    except ValueError as e:
        logger.warning(f"Error parsing datetime '{iso_string}': {e}")
        return datetime.now()
