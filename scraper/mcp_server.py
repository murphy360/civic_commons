"""
MCP Server for Civic Commons Event Management

This server provides tools for an AI to intelligently manage events:
- Query existing events by date/title/similarity
- Create new events
- Add sources to existing events (deduplication)
- Update event details

The AI uses these tools to decide whether incoming event data
should create a new event or be linked to an existing one.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import asyncpg
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("civic_mcp")

# Database connection
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://commons:password@localhost:5432/civic_commons"
)

app = Server("civic-events")


async def get_db_pool() -> asyncpg.Pool:
    """Get or create database connection pool."""
    if not hasattr(get_db_pool, "_pool"):
        get_db_pool._pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return get_db_pool._pool


# =============================================================================
# Tool Definitions
# =============================================================================

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools for event management."""
    return [
        Tool(
            name="search_events",
            description="""Search for events by date range and/or keywords.
Use this to find existing events before creating new ones.
Returns events with their sources and similarity scores.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD). Defaults to today."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD). Defaults to 30 days from start."
                    },
                    "keywords": {
                        "type": "string",
                        "description": "Keywords to search in event titles"
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category (meeting, recreation, community, etc.)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default 20)"
                    }
                }
            }
        ),
        Tool(
            name="find_similar_events",
            description="""Find events similar to a given title and date.
Use this to check if an incoming event already exists before creating it.
Uses fuzzy matching on titles within a time window.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Event title to match"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Event start time (ISO format: YYYY-MM-DDTHH:MM:SS)"
                    },
                    "time_window_hours": {
                        "type": "integer",
                        "description": "Hours before/after to search (default 4)"
                    }
                },
                "required": ["title", "start_time"]
            }
        ),
        Tool(
            name="get_event_details",
            description="""Get full details of a specific event including all sources.
Use this to see complete information about an event.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "integer",
                        "description": "Event ID to retrieve"
                    }
                },
                "required": ["event_id"]
            }
        ),
        Tool(
            name="create_event",
            description="""Create a new event. Only use this if find_similar_events
returned no matches. Returns the new event ID.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Event title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time (ISO format)"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time (ISO format, optional)"
                    },
                    "location": {
                        "type": "string",
                        "description": "Event location"
                    },
                    "category": {
                        "type": "string",
                        "description": "Category (meeting, recreation, community, library, etc.)"
                    },
                    "source_name": {
                        "type": "string",
                        "description": "Name of the source reporting this event"
                    },
                    "source_url": {
                        "type": "string",
                        "description": "URL to event on source website"
                    },
                    "external_id": {
                        "type": "string",
                        "description": "ID used by the source for this event"
                    }
                },
                "required": ["title", "start_time", "source_name"]
            }
        ),
        Tool(
            name="add_source_to_event",
            description="""Link an additional source to an existing event.
Use this when find_similar_events found a match - adds the new source
to the existing event rather than creating a duplicate.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "integer",
                        "description": "Existing event ID to link to"
                    },
                    "source_name": {
                        "type": "string",
                        "description": "Name of the source"
                    },
                    "source_url": {
                        "type": "string",
                        "description": "URL to event on this source"
                    },
                    "external_id": {
                        "type": "string",
                        "description": "ID used by the source for this event"
                    },
                    "raw_data": {
                        "type": "object",
                        "description": "Original data from this source (optional)"
                    }
                },
                "required": ["event_id", "source_name"]
            }
        ),
        Tool(
            name="update_event",
            description="""Update an existing event's details.
Use this to improve event data (better description, add location, etc.)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "integer",
                        "description": "Event ID to update"
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "category": {"type": "string"},
                    "is_cancelled": {"type": "boolean"},
                    "is_virtual": {"type": "boolean"},
                    "virtual_url": {"type": "string"},
                    "video_url": {"type": "string"}
                },
                "required": ["event_id"]
            }
        ),
        Tool(
            name="process_event_batch",
            description="""Process a batch of events from a scraper.
For each event, automatically finds similar events and either
creates new or links to existing. Returns summary of actions taken.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_name": {
                        "type": "string",
                        "description": "Name of the source these events come from"
                    },
                    "events": {
                        "type": "array",
                        "description": "Array of event objects to process",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "start_time": {"type": "string"},
                                "end_time": {"type": "string"},
                                "location": {"type": "string"},
                                "category": {"type": "string"},
                                "source_url": {"type": "string"},
                                "external_id": {"type": "string"}
                            },
                            "required": ["title", "start_time"]
                        }
                    }
                },
                "required": ["source_name", "events"]
            }
        ),
        Tool(
            name="link_legislation",
            description="""Link legislation (ordinance, resolution, etc.) to a meeting/document.
Call this when AI extracts legislation mentions from a document to create
structured records of what legislation was discussed and what action was taken.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "integer",
                        "description": "The document ID where legislation was mentioned"
                    },
                    "event_id": {
                        "type": "integer",
                        "description": "The event (meeting) ID this document is linked to (optional)"
                    },
                    "legislation_type": {
                        "type": "string",
                        "description": "Type of legislation: 'ordinance', 'resolution', 'motion', 'bylaw', 'proclamation'"
                    },
                    "legislation_number": {
                        "type": "string",
                        "description": "Legislation number/identifier (e.g., '2025-139', 'R-2025-12')"
                    },
                    "legislation_title": {
                        "type": "string",
                        "description": "Full title of the legislation (optional)"
                    },
                    "action_taken": {
                        "type": "string",
                        "description": "Action taken: 'introduced', 'first_reading', 'second_reading', 'third_reading', 'public_hearing', 'amended', 'tabled', 'referred', 'approved', 'failed', 'vetoed', 'withdrawn', 'discussed'"
                    },
                    "vote_result": {
                        "type": "string",
                        "description": "Result of vote if one occurred: 'passed', 'failed', 'tabled', 'unanimous' (optional)"
                    },
                    "vote_details": {
                        "type": "object",
                        "description": "Vote breakdown: {\"yes\": 5, \"no\": 2, \"abstain\": 0, \"absent\": 0} (optional)"
                    },
                    "excerpt": {
                        "type": "string",
                        "description": "Relevant excerpt from the document (optional)"
                    }
                },
                "required": ["document_id", "legislation_type", "legislation_number", "action_taken"]
            }
        ),
        Tool(
            name="find_legislation_mentions",
            description="""Search for all mentions of a specific piece of legislation across meetings.
Returns the complete history of an ordinance/resolution including when it was
discussed, what actions were taken, and vote results.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "legislation_number": {
                        "type": "string",
                        "description": "Legislation number to search for (e.g., '2025-139')"
                    }
                },
                "required": ["legislation_number"]
            }
        ),
        Tool(
            name="reanalyze_documents",
            description="""Clear AI summaries and legislation mentions from documents to trigger re-analysis.
Use this when you need to reprocess documents for updated legislation extraction.
Can target specific documents by ID, or recent documents by date range.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Specific document IDs to reanalyze"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Reanalyze documents from the last N days (default 30)"
                    },
                    "document_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by document types: 'agenda', 'minutes', 'packet' (default: all meeting docs)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum documents to reanalyze (default 20, max 100)"
                    }
                }
            }
        ),
        Tool(
            name="get_document_analysis_status",
            description="""Get the current status of document analysis including counts of
documents pending summaries, documents with legislation mentions, and recent analysis activity.""",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


# =============================================================================
# Tool Implementations
# =============================================================================

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    pool = await get_db_pool()
    
    try:
        if name == "search_events":
            result = await search_events(pool, arguments)
        elif name == "find_similar_events":
            result = await find_similar_events(pool, arguments)
        elif name == "get_event_details":
            result = await get_event_details(pool, arguments)
        elif name == "create_event":
            result = await create_event(pool, arguments)
        elif name == "add_source_to_event":
            result = await add_source_to_event(pool, arguments)
        elif name == "update_event":
            result = await update_event(pool, arguments)
        elif name == "process_event_batch":
            result = await process_event_batch(pool, arguments)
        elif name == "link_legislation":
            result = await link_legislation(pool, arguments)
        elif name == "find_legislation_mentions":
            result = await find_legislation_mentions(pool, arguments)
        elif name == "reanalyze_documents":
            result = await reanalyze_documents(pool, arguments)
        elif name == "get_document_analysis_status":
            result = await get_document_analysis_status(pool, arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]
    
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def search_events(pool: asyncpg.Pool, args: dict) -> dict:
    """Search events by date range and keywords."""
    start_date = args.get("start_date", datetime.now().strftime("%Y-%m-%d"))
    end_date = args.get("end_date")
    keywords = args.get("keywords")
    category = args.get("category")
    limit = args.get("limit", 20)
    
    if not end_date:
        end_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=30)
        end_date = end_dt.strftime("%Y-%m-%d")
    
    async with pool.acquire() as conn:
        query = """
            SELECT 
                e.id, e.title, e.description, e.start_time, e.end_time,
                e.location, e.category, e.is_cancelled,
                array_agg(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL) as sources,
                COUNT(DISTINCT es.source_id) as source_count
            FROM events e
            LEFT JOIN event_sources es ON e.id = es.event_id
            LEFT JOIN sources s ON es.source_id = s.id
            WHERE e.start_time >= $1::date AND e.start_time < $2::date + interval '1 day'
        """
        params = [start_date, end_date]
        param_idx = 3
        
        if keywords:
            query += f" AND e.title ILIKE ${param_idx}"
            params.append(f"%{keywords}%")
            param_idx += 1
        
        if category:
            query += f" AND e.category = ${param_idx}"
            params.append(category)
            param_idx += 1
        
        query += f"""
            GROUP BY e.id
            ORDER BY e.start_time
            LIMIT ${param_idx}
        """
        params.append(limit)
        
        rows = await conn.fetch(query, *params)
        
        return {
            "count": len(rows),
            "events": [dict(row) for row in rows]
        }


async def find_similar_events(pool: asyncpg.Pool, args: dict) -> dict:
    """Find events similar to given title and date."""
    title = args["title"]
    start_time = args["start_time"]
    time_window = args.get("time_window_hours", 4)
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM find_similar_events($1, $2::timestamp, $3 * interval '1 hour')
            """,
            title, start_time, time_window
        )
        
        matches = [dict(row) for row in rows]
        
        return {
            "query": {"title": title, "start_time": start_time},
            "matches_found": len(matches),
            "matches": matches,
            "recommendation": "create_new" if not matches else (
                "add_source" if matches[0]["similarity"] > 0.6 else "review_manually"
            )
        }


async def get_event_details(pool: asyncpg.Pool, args: dict) -> dict:
    """Get full event details with all sources."""
    event_id = args["event_id"]
    
    async with pool.acquire() as conn:
        event = await conn.fetchrow(
            """
            SELECT * FROM events WHERE id = $1
            """,
            event_id
        )
        
        if not event:
            return {"error": f"Event {event_id} not found"}
        
        sources = await conn.fetch(
            """
            SELECT es.*, s.name as source_name
            FROM event_sources es
            JOIN sources s ON es.source_id = s.id
            WHERE es.event_id = $1
            """,
            event_id
        )
        
        documents = await conn.fetch(
            """
            SELECT d.id, d.title, d.document_type, d.source_url, d.local_path,
                   ed.relationship
            FROM documents d
            JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.event_id = $1
            """,
            event_id
        )
        
        return {
            "event": dict(event),
            "sources": [dict(s) for s in sources],
            "documents": [dict(d) for d in documents]
        }


async def create_event(pool: asyncpg.Pool, args: dict) -> dict:
    """Create a new event and link to source."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Get or create source
            source = await conn.fetchrow(
                "SELECT id FROM sources WHERE name = $1",
                args["source_name"]
            )
            if not source:
                return {"error": f"Source '{args['source_name']}' not found"}
            source_id = source["id"]
            
            # Create event
            event_id = await conn.fetchval(
                """
                INSERT INTO events (title, description, start_time, end_time, location, category)
                VALUES ($1, $2, $3::timestamp, $4::timestamp, $5, $6)
                RETURNING id
                """,
                args["title"],
                args.get("description"),
                args["start_time"],
                args.get("end_time"),
                args.get("location"),
                args.get("category")
            )
            
            # Link to source
            await conn.execute(
                """
                INSERT INTO event_sources (event_id, source_id, external_id, source_url)
                VALUES ($1, $2, $3, $4)
                """,
                event_id,
                source_id,
                args.get("external_id"),
                args.get("source_url")
            )
            
            return {
                "success": True,
                "event_id": event_id,
                "action": "created",
                "message": f"Created event '{args['title']}' (ID: {event_id})"
            }


async def add_source_to_event(pool: asyncpg.Pool, args: dict) -> dict:
    """Add a source to an existing event."""
    async with pool.acquire() as conn:
        # Get source ID
        source = await conn.fetchrow(
            "SELECT id FROM sources WHERE name = $1",
            args["source_name"]
        )
        if not source:
            return {"error": f"Source '{args['source_name']}' not found"}
        source_id = source["id"]
        
        # Check if event exists
        event = await conn.fetchrow(
            "SELECT id, title FROM events WHERE id = $1",
            args["event_id"]
        )
        if not event:
            return {"error": f"Event {args['event_id']} not found"}
        
        # Add source link (upsert)
        await conn.execute(
            """
            INSERT INTO event_sources (event_id, source_id, external_id, source_url, raw_data)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (event_id, source_id) DO UPDATE SET
                source_url = COALESCE(EXCLUDED.source_url, event_sources.source_url),
                external_id = COALESCE(EXCLUDED.external_id, event_sources.external_id),
                raw_data = COALESCE(EXCLUDED.raw_data, event_sources.raw_data),
                last_seen_at = NOW()
            """,
            args["event_id"],
            source_id,
            args.get("external_id"),
            args.get("source_url"),
            json.dumps(args.get("raw_data")) if args.get("raw_data") else None
        )
        
        return {
            "success": True,
            "event_id": args["event_id"],
            "action": "linked",
            "message": f"Linked source '{args['source_name']}' to event '{event['title']}'"
        }


async def update_event(pool: asyncpg.Pool, args: dict) -> dict:
    """Update event details."""
    event_id = args.pop("event_id")
    
    if not args:
        return {"error": "No fields to update"}
    
    # Build dynamic update query
    set_clauses = []
    params = []
    param_idx = 1
    
    allowed_fields = ["title", "description", "location", "category", 
                      "is_cancelled", "is_virtual", "virtual_url", "video_url"]
    
    for field in allowed_fields:
        if field in args:
            set_clauses.append(f"{field} = ${param_idx}")
            params.append(args[field])
            param_idx += 1
    
    if not set_clauses:
        return {"error": "No valid fields to update"}
    
    params.append(event_id)
    
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"""
            UPDATE events SET {', '.join(set_clauses)}, updated_at = NOW()
            WHERE id = ${param_idx}
            """,
            *params
        )
        
        return {
            "success": True,
            "event_id": event_id,
            "updated_fields": list(args.keys())
        }


async def process_event_batch(pool: asyncpg.Pool, args: dict) -> dict:
    """Process a batch of events, deduplicating as needed."""
    source_name = args["source_name"]
    events = args["events"]
    
    results = {
        "source": source_name,
        "total": len(events),
        "created": 0,
        "linked": 0,
        "errors": 0,
        "details": []
    }
    
    for event_data in events:
        try:
            # First, check for similar events
            similar = await find_similar_events(pool, {
                "title": event_data["title"],
                "start_time": event_data["start_time"],
                "time_window_hours": 4
            })
            
            if similar["matches"] and similar["matches"][0]["similarity"] > 0.5:
                # Link to existing event
                match = similar["matches"][0]
                result = await add_source_to_event(pool, {
                    "event_id": match["event_id"],
                    "source_name": source_name,
                    "source_url": event_data.get("source_url"),
                    "external_id": event_data.get("external_id")
                })
                results["linked"] += 1
                results["details"].append({
                    "title": event_data["title"],
                    "action": "linked",
                    "matched_event_id": match["event_id"],
                    "similarity": match["similarity"]
                })
            else:
                # Create new event
                result = await create_event(pool, {
                    **event_data,
                    "source_name": source_name
                })
                results["created"] += 1
                results["details"].append({
                    "title": event_data["title"],
                    "action": "created",
                    "event_id": result.get("event_id")
                })
                
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "title": event_data.get("title", "unknown"),
                "action": "error",
                "error": str(e)
            })
    
    return results


async def link_legislation(pool: asyncpg.Pool, args: dict) -> dict:
    """Link legislation to a document and optionally an event.
    
    Creates or updates a record in the legislation_mentions table.
    """
    document_id = args["document_id"]
    legislation_type = args["legislation_type"]
    legislation_number = args["legislation_number"]
    action_taken = args["action_taken"]
    
    event_id = args.get("event_id")
    legislation_title = args.get("legislation_title")
    vote_result = args.get("vote_result")
    vote_details = args.get("vote_details")
    excerpt = args.get("excerpt")
    
    async with pool.acquire() as conn:
        # First, get the document to get its meeting_date
        doc = await conn.fetchrow(
            "SELECT id, meeting_date FROM documents WHERE id = $1",
            document_id
        )
        
        if not doc:
            return {"error": f"Document {document_id} not found"}
        
        mentioned_date = doc["meeting_date"]
        
        # Check if this mention already exists
        existing = await conn.fetchrow("""
            SELECT id FROM legislation_mentions
            WHERE document_id = $1
              AND legislation_number = $2
              AND action_taken = $3
        """, document_id, legislation_number, action_taken)
        
        if existing:
            # Update existing mention
            mention_id = existing["id"]
            await conn.execute("""
                UPDATE legislation_mentions
                SET legislation_title = COALESCE($2, legislation_title),
                    vote_result = COALESCE($3, vote_result),
                    vote_details = COALESCE($4, vote_details),
                    excerpt = COALESCE($5, excerpt),
                    event_id = COALESCE($6, event_id),
                    updated_at = NOW()
                WHERE id = $1
            """, mention_id, legislation_title, vote_result, 
                json.dumps(vote_details) if vote_details else None,
                excerpt, event_id)
            
            action = "updated"
        else:
            # Create new mention
            mention_id = await conn.fetchval("""
                INSERT INTO legislation_mentions (
                    document_id,
                    event_id,
                    legislation_type,
                    legislation_number,
                    legislation_title,
                    action_taken,
                    vote_result,
                    vote_details,
                    excerpt,
                    mentioned_date
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
            """, document_id, event_id, legislation_type, legislation_number,
                legislation_title, action_taken, vote_result,
                json.dumps(vote_details) if vote_details else None,
                excerpt, mentioned_date)
            
            action = "created"
        
        return {
            "success": True,
            "action": action,
            "mention_id": mention_id,
            "legislation_number": legislation_number,
            "legislation_type": legislation_type,
            "action_taken": action_taken,
            "document_id": document_id,
            "event_id": event_id,
            "mentioned_date": mentioned_date.isoformat() if mentioned_date else None
        }


async def find_legislation_mentions(pool: asyncpg.Pool, args: dict) -> dict:
    """Find all mentions of a specific piece of legislation across meetings.
    
    Returns the complete history including documents, events, actions, and votes.
    """
    legislation_number = args["legislation_number"]
    
    async with pool.acquire() as conn:
        mentions = await conn.fetch("""
            SELECT 
                lm.id,
                lm.document_id,
                d.title as document_title,
                d.document_type,
                lm.event_id,
                e.title as event_title,
                e.start_time as event_time,
                lm.legislation_type,
                lm.legislation_title,
                lm.action_taken,
                lm.vote_result,
                lm.vote_details,
                lm.excerpt,
                lm.mentioned_date,
                s.name as source_name
            FROM legislation_mentions lm
            JOIN documents d ON lm.document_id = d.id
            JOIN sources s ON d.source_id = s.id
            LEFT JOIN events e ON lm.event_id = e.id
            WHERE lm.legislation_number ILIKE $1
            ORDER BY lm.mentioned_date ASC NULLS LAST, lm.created_at ASC
        """, legislation_number)
        
        if not mentions:
            return {
                "legislation_number": legislation_number,
                "found": False,
                "mentions": []
            }
        
        # Group by unique legislation info
        legislation_info = {
            "type": mentions[0]["legislation_type"],
            "number": legislation_number,
            "title": mentions[0]["legislation_title"]
        }
        
        # Serialize mentions for JSON response
        serialized_mentions = []
        for m in mentions:
            mention = {
                "mention_id": m["id"],
                "document_id": m["document_id"],
                "document_title": m["document_title"],
                "document_type": m["document_type"],
                "source_name": m["source_name"],
                "event_id": m["event_id"],
                "event_title": m["event_title"],
                "event_time": m["event_time"].isoformat() if m["event_time"] else None,
                "action_taken": m["action_taken"],
                "vote_result": m["vote_result"],
                "vote_details": m["vote_details"],  # Already a dict from DB
                "excerpt": m["excerpt"],
                "mentioned_date": m["mentioned_date"].isoformat() if m["mentioned_date"] else None
            }
            serialized_mentions.append(mention)
        
        # Extract timeline of actions
        timeline = []
        for m in mentions:
            timeline.append({
                "date": m["mentioned_date"].isoformat() if m["mentioned_date"] else m["created_at"].isoformat() if hasattr(m, "created_at") else None,
                "action": m["action_taken"],
                "event": m["event_title"],
                "vote": m["vote_result"],
                "document": m["document_title"]
            })
        
        return {
            "legislation": legislation_info,
            "found": True,
            "mention_count": len(mentions),
            "timeline": timeline,
            "mentions": serialized_mentions
        }


async def reanalyze_documents(pool: asyncpg.Pool, args: dict) -> dict:
    """Clear AI summaries and legislation mentions to trigger re-analysis.
    
    Can target specific documents or recent documents by date.
    """
    document_ids = args.get("document_ids")
    days_back = args.get("days_back", 30)
    document_types = args.get("document_types", ["agenda", "minutes", "packet"])
    limit = min(args.get("limit", 20), 100)  # Cap at 100
    
    async with pool.acquire() as conn:
        if document_ids:
            # Specific documents requested
            docs = await conn.fetch("""
                SELECT id, title, document_type, meeting_date
                FROM documents
                WHERE id = ANY($1::int[])
            """, document_ids)
        else:
            # Recent documents by date
            docs = await conn.fetch("""
                SELECT id, title, document_type, meeting_date
                FROM documents
                WHERE document_type = ANY($1::text[])
                  AND ai_summary IS NOT NULL 
                  AND ai_summary != ''
                  AND (meeting_date >= NOW() - INTERVAL '1 day' * $2 OR meeting_date IS NULL)
                ORDER BY meeting_date DESC NULLS LAST
                LIMIT $3
            """, document_types, days_back, limit)
        
        if not docs:
            return {
                "success": False,
                "message": "No matching documents found",
                "cleared": 0
            }
        
        doc_ids = [doc["id"] for doc in docs]
        
        # Clear legislation mentions for these documents
        mentions_deleted = await conn.fetchval("""
            DELETE FROM legislation_mentions
            WHERE document_id = ANY($1::int[])
            RETURNING COUNT(*)
        """, doc_ids) or 0
        
        # Clear AI summaries to trigger re-analysis
        await conn.execute("""
            UPDATE documents
            SET ai_summary = NULL
            WHERE id = ANY($1::int[])
        """, doc_ids)
        
        return {
            "success": True,
            "message": f"Cleared {len(docs)} documents for re-analysis",
            "documents_cleared": len(docs),
            "legislation_mentions_removed": mentions_deleted,
            "documents": [
                {
                    "id": doc["id"],
                    "title": doc["title"],
                    "type": doc["document_type"],
                    "meeting_date": doc["meeting_date"].isoformat() if doc["meeting_date"] else None
                }
                for doc in docs
            ]
        }


async def get_document_analysis_status(pool: asyncpg.Pool, args: dict) -> dict:
    """Get current status of document analysis pipeline."""
    async with pool.acquire() as conn:
        # Count documents by summary status
        summary_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_documents,
                COUNT(CASE WHEN ai_summary IS NOT NULL AND ai_summary != '' THEN 1 END) as with_summary,
                COUNT(CASE WHEN ai_summary IS NULL OR ai_summary = '' THEN 1 END) as pending_summary
            FROM documents
            WHERE document_type IN ('agenda', 'minutes', 'packet')
              AND local_path IS NOT NULL
        """)
        
        # Count legislation mentions
        legislation_stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_mentions,
                COUNT(DISTINCT document_id) as documents_with_mentions,
                COUNT(DISTINCT legislation_number) as unique_legislation
            FROM legislation_mentions
        """)
        
        # Recent analysis activity
        recent_mentions = await conn.fetch("""
            SELECT 
                lm.legislation_type,
                lm.legislation_number,
                lm.action_taken,
                d.title as document_title,
                lm.created_at
            FROM legislation_mentions lm
            JOIN documents d ON lm.document_id = d.id
            ORDER BY lm.created_at DESC
            LIMIT 10
        """)
        
        return {
            "document_summary_status": {
                "total_meeting_documents": summary_stats["total_documents"],
                "with_summary": summary_stats["with_summary"],
                "pending_summary": summary_stats["pending_summary"],
                "completion_percent": round(
                    100 * summary_stats["with_summary"] / max(summary_stats["total_documents"], 1), 1
                )
            },
            "legislation_extraction": {
                "total_mentions": legislation_stats["total_mentions"],
                "documents_with_mentions": legislation_stats["documents_with_mentions"],
                "unique_legislation_items": legislation_stats["unique_legislation"]
            },
            "recent_extractions": [
                {
                    "type": m["legislation_type"],
                    "number": m["legislation_number"],
                    "action": m["action_taken"],
                    "from_document": m["document_title"],
                    "extracted_at": m["created_at"].isoformat()
                }
                for m in recent_mentions
            ]
        }


# =============================================================================
# Main
# =============================================================================

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
