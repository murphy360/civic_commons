"""
MCP Handlers for Civic Commons

This package provides handlers for the MCP (Model Context Protocol) server
that allows AI models to manage civic events, documents, and legislation.

Modules:
- tools: Tool schema definitions
- event_handlers: Event management handlers
- document_handlers: Document and legislation handlers
- server: Main MCP server entry point
"""

from .tools import get_tool_definitions
from .event_handlers import (
    search_events,
    find_similar_events,
    get_event_details,
    create_event,
    add_source_to_event,
    update_event,
    process_event_batch,
)
from .document_handlers import (
    link_legislation,
    find_legislation_mentions,
    reanalyze_documents,
    get_document_analysis_status,
)

__all__ = [
    # Tool definitions
    "get_tool_definitions",
    # Event handlers
    "search_events",
    "find_similar_events",
    "get_event_details",
    "create_event",
    "add_source_to_event",
    "update_event",
    "process_event_batch",
    # Legislation handlers
    "link_legislation",
    "find_legislation_mentions",
    # Document handlers
    "reanalyze_documents",
    "get_document_analysis_status",
]

