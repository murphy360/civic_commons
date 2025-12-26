"""
Unified Tool Registry for Civic Commons

Consolidates all tools (MCP, chat, and scraper) into a single registry
with role-based access control.

Access Levels:
- read_only: Safe for Gemini function calling (no data modification)
- write_internal: Restricted to internal pipeline (scraper, event creation)
- admin: Administrative operations (future expansion)

Categories:
- event: Event management and querying
- document: Document search and retrieval
- legislative: Legislation tracking and searching
- system: Health, configuration, manifest
"""

from typing import Any, Literal

AccessLevel = Literal["read_only", "write_internal", "admin"]
ToolCategory = Literal["event", "document", "legislative", "system", "tool_call"]


class ToolDefinition:
    """Schema for a tool definition."""
    
    def __init__(
        self,
        name: str,
        description: str,
        access_level: AccessLevel,
        category: ToolCategory,
        parameters: dict[str, Any],
        handler_path: str,
    ):
        self.name = name
        self.description = description
        self.access_level = access_level
        self.category = category
        self.parameters = parameters
        self.handler_path = handler_path  # e.g., "server.tools.get_commons_calendar"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for MCP/Gemini transport."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
    
    def to_gemini_format(self) -> dict[str, Any]:
        """Convert to Gemini function calling format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters.get("properties", {}),
                "required": self.parameters.get("required", []),
            },
        }


# Unified Tool Registry
TOOLS: dict[str, ToolDefinition] = {
    # =========================================================================
    # READ-ONLY TOOLS (Safe for Gemini, MCP clients)
    # =========================================================================
    
    "get_events": ToolDefinition(
        name="get_events",
        description="Search for upcoming or past events and meetings. Find city council meetings, school board meetings, library events, and community activities.",
        access_level="read_only",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier (e.g., 'twinsburg')",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format. Defaults to today.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Defaults to 30 days from start.",
                },
                "source_name": {
                    "type": "string",
                    "description": "Filter by source name (partial match). Examples: 'Library', 'City Council', 'School'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of events to return. Default 20.",
                },
            },
            "required": ["city_id"],
        },
        handler_path="server.tools.get_commons_calendar",
    ),
    
    "search_documents": ToolDefinition(
        name="search_documents",
        description="Search meeting minutes, agendas, and civic documents by keyword or topic.",
        access_level="read_only",
        category="document",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier (e.g., 'twinsburg')",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (keywords, topics, natural language)",
                },
                "source_type": {
                    "type": "string",
                    "description": "Filter by source type (city_council, school_board, etc.)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results. Default 10.",
                },
            },
            "required": ["city_id", "query"],
        },
        handler_path="server.tools.search_commons_records",
    ),
    
    "get_document_content": ToolDefinition(
        name="get_document_content",
        description="Get the full content of a specific document by ID. Use after searching to read document details.",
        access_level="read_only",
        category="document",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier",
                },
                "document_id": {
                    "type": "integer",
                    "description": "The document ID to retrieve",
                },
            },
            "required": ["city_id", "document_id"],
        },
        handler_path="db.get_document_content",
    ),
    
    "find_legislation": ToolDefinition(
        name="find_legislation",
        description="Search for legislation mentions (ordinances, resolutions, motions) and their status.",
        access_level="read_only",
        category="legislative",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier",
                },
                "legislation_type": {
                    "type": "string",
                    "description": "Type: ordinance, resolution, motion, proclamation",
                },
                "legislation_number": {
                    "type": "string",
                    "description": "Legislation number (e.g., '2025-01', 'R-2025-12')",
                },
                "search_text": {
                    "type": "string",
                    "description": "Text to search in legislation titles",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results. Default 20.",
                },
            },
            "required": ["city_id"],
        },
        handler_path="chat.find_legislation",
    ),
    
    "get_commons_calendar": ToolDefinition(
        name="get_commons_calendar",
        description="Get community events within a date range. Find meetings, events, and activities.",
        access_level="read_only",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format",
                },
                "source_type": {
                    "type": "string",
                    "description": "Filter by source type",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum events to return",
                },
            },
            "required": ["city_id"],
        },
        handler_path="server.tools.get_commons_calendar",
    ),
    
    "search_commons_records": ToolDefinition(
        name="search_commons_records",
        description="Search community documents and records by keyword.",
        access_level="read_only",
        category="document",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier",
                },
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "source_type": {
                    "type": "string",
                    "description": "Filter by source type",
                },
                "include_content": {
                    "type": "boolean",
                    "description": "Include full document content",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results",
                },
            },
            "required": ["city_id", "query"],
        },
        handler_path="server.tools.search_commons_records",
    ),
    
    "get_assistant_manifest": ToolDefinition(
        name="get_assistant_manifest",
        description="Get assistant configuration (name, persona, city info).",
        access_level="read_only",
        category="system",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier",
                },
            },
            "required": ["city_id"],
        },
        handler_path="tools.get_assistant_manifest",
    ),
    
    "get_source_health": ToolDefinition(
        name="get_source_health",
        description="Get health status of data sources (freshness, availability).",
        access_level="read_only",
        category="system",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {
                    "type": "string",
                    "description": "City identifier",
                },
            },
            "required": ["city_id"],
        },
        handler_path="tools.get_source_health",
    ),
    
    # =========================================================================
    # WRITE-INTERNAL TOOLS (Restricted to internal pipeline)
    # =========================================================================
    
    "upsert_event": ToolDefinition(
        name="upsert_event",
        description="Create or merge an event with AI-powered deduplication. Creates new event or merges with existing based on similarity and AI verification.",
        access_level="write_internal",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "integer",
                    "description": "ID of the event source (city council, library, etc.)",
                },
                "title": {
                    "type": "string",
                    "description": "Event title (required)",
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in ISO format (YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD)",
                },
                "location": {
                    "type": "string",
                    "description": "Event location",
                },
                "description": {
                    "type": "string",
                    "description": "Event description/details",
                },
                "end_time": {
                    "type": "string",
                    "description": "End time in ISO format",
                },
                "category": {
                    "type": "string",
                    "description": "Event category (meeting, hearing, workshop, etc.)",
                },
                "is_virtual": {
                    "type": "boolean",
                    "description": "Whether event is virtual",
                },
                "virtual_url": {
                    "type": "string",
                    "description": "URL for virtual events",
                },
                "external_id": {
                    "type": "string",
                    "description": "External ID from source system for dedup",
                },
                "source_url": {
                    "type": "string",
                    "description": "URL to the event on source website",
                },
            },
            "required": ["source_id", "title", "start_time"],
        },
        handler_path="tools.upsert_event",
    ),
    
    "create_event": ToolDefinition(
        name="create_event",
        description="Create a new event record (internal only).",
        access_level="write_internal",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {"type": "string"},
                "title": {"type": "string"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "location": {"type": "string"},
                "description": {"type": "string"},
                "category": {"type": "string"},
                "source_id": {"type": "integer"},
                "external_id": {"type": "string"},
            },
            "required": ["city_id", "title", "start_time"],
        },
        handler_path="scraper.pipeline.storage.create_event",
    ),
    
    "update_event": ToolDefinition(
        name="update_event",
        description="Update existing event details (internal only).",
        access_level="write_internal",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "location": {"type": "string"},
                "ai_summary": {"type": "string"},
            },
            "required": ["event_id"],
        },
        handler_path="scraper.pipeline.storage.update_event",
    ),
    
    "add_source_to_event": ToolDefinition(
        name="add_source_to_event",
        description="Link a data source to an event (internal only).",
        access_level="write_internal",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "source_id": {"type": "integer"},
                "external_id": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": ["event_id", "source_id"],
        },
        handler_path="scraper.pipeline.storage.add_event_source",
    ),
    
    "link_document_to_event": ToolDefinition(
        name="link_document_to_event",
        description="Associate a document with an event (internal only).",
        access_level="write_internal",
        category="document",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "document_id": {"type": "integer"},
                "relationship": {
                    "type": "string",
                    "description": "Type of relationship (agenda, minutes, summary, etc.)",
                },
            },
            "required": ["event_id", "document_id"],
        },
        handler_path="scraper.pipeline.storage.link_document_to_event",
    ),
    
    "validate_event": ToolDefinition(
        name="validate_event",
        description="Validate event quality and completeness (internal only).",
        access_level="write_internal",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
            },
            "required": ["event_id"],
        },
        handler_path="tools.validate_event",
    ),
    
    "find_duplicate_events": ToolDefinition(
        name="find_duplicate_events",
        description="Find duplicate events by similarity (internal only).",
        access_level="write_internal",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "city_id": {"type": "string"},
                "event_id": {"type": "integer"},
                "similarity_threshold": {
                    "type": "number",
                    "description": "Threshold 0.0-1.0 for duplicate detection",
                },
            },
            "required": ["city_id", "event_id"],
        },
        handler_path="tools.find_duplicate_events",
    ),
    
    "enrich_event_data": ToolDefinition(
        name="enrich_event_data",
        description="Add AI-generated metadata to events (internal only).",
        access_level="write_internal",
        category="event",
        parameters={
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "ai_summary": {"type": "string"},
                "key_topics": {"type": "array", "items": {"type": "string"}},
                "sentiment": {"type": "string"},
                "importance_score": {"type": "number"},
            },
            "required": ["event_id"],
        },
        handler_path="tools.enrich_event_data",
    ),
}


def get_tool_definitions(access_level: AccessLevel | None = None) -> dict[str, ToolDefinition]:
    """
    Get tool definitions filtered by access level.
    
    Args:
        access_level: Filter by access level. None returns all tools.
        
    Returns:
        Dictionary of tool name -> ToolDefinition
    """
    if access_level is None:
        return TOOLS
    
    return {name: tool for name, tool in TOOLS.items() if tool.access_level == access_level}


def get_tools_for_gemini(city_id: str) -> dict[str, Any]:
    """
    Get tool definitions in Gemini function calling format.
    Only includes read-only tools (safe for LLM usage).
    
    Args:
        city_id: City context (for filtering if needed)
        
    Returns:
        Dictionary of tool name -> Gemini format definition
    """
    gemini_tools = {}
    read_only_tools = get_tool_definitions("read_only")
    
    for name, tool in read_only_tools.items():
        gemini_tools[name] = tool.to_gemini_format()
    
    return gemini_tools


def get_tools_for_mcp(access_level: AccessLevel = "read_only") -> dict[str, Any]:
    """
    Get tool definitions in MCP format.
    
    Args:
        access_level: Access level to return tools for
        
    Returns:
        Dictionary of tool name -> MCP format definition
    """
    mcp_tools = {}
    tools = get_tool_definitions(access_level)
    
    for name, tool in tools.items():
        mcp_tools[name] = tool.to_dict()
    
    return mcp_tools


def list_tools(access_level: AccessLevel | None = None, category: ToolCategory | None = None) -> list[dict[str, Any]]:
    """
    List all tools with metadata.
    
    Args:
        access_level: Filter by access level
        category: Filter by category
        
    Returns:
        List of tool metadata dictionaries
    """
    tools = get_tool_definitions(access_level)
    
    result = []
    for name, tool in tools.items():
        if category is not None and tool.category != category:
            continue
        
        result.append({
            "name": name,
            "description": tool.description,
            "access_level": tool.access_level,
            "category": tool.category,
            "parameters": tool.parameters,
        })
    
    return result


