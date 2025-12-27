"""
Civic Commons MCP Server - Tool Definitions

Defines the MCP tools exposed to LLM clients.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

# shared is copied to services/shared by Dockerfile
from ..shared.db import Database

logger = logging.getLogger("civic_commons.tools")


def register_tools(mcp: FastMCP, db: Database, ai_processor: Optional[Any] = None) -> None:
    """
    Register all MCP tools with the server.
    
    Args:
        mcp: The FastMCP server instance
        db: The database instance
        ai_processor: Optional AIEventProcessor for event deduplication
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
            "timezone": config.get("timezone"),  # Should come from config
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

    # ─────────────────────────────────────────────────────────────────
    # AI Event Processing Tools
    # ─────────────────────────────────────────────────────────────────
    
    @mcp.tool()
    async def validate_event(
        title: str,
        description: str | None = None,
        start_time: str | None = None,
        location: str | None = None,
        source_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Validate a civic event for quality and completeness.
        
        Use this tool to check if an event has all required information
        and appears to be a legitimate civic event. Returns validation
        results and suggestions for improvement.
        
        Args:
            title: The event title
            description: Optional event description
            start_time: Optional ISO datetime string
            location: Optional location/address
            source_name: Optional name of the data source
            
        Returns:
            Dictionary containing validation results:
            - is_valid: Boolean indicating if event passes validation
            - confidence: Float 0-1 indicating confidence
            - issues: List of validation issues found
            - suggestions: List of improvement suggestions
            - category: Detected event category
        """
        issues = []
        suggestions = []
        confidence = 1.0
        
        # Title validation
        if not title or len(title.strip()) < 5:
            issues.append("Title is too short or missing")
            confidence -= 0.3
        elif len(title) > 200:
            issues.append("Title is unusually long")
            suggestions.append("Consider shortening the title")
            confidence -= 0.1
            
        # Check for spam indicators in title
        spam_indicators = ["click here", "buy now", "free money", "limited time"]
        if title and any(spam in title.lower() for spam in spam_indicators):
            issues.append("Title contains potential spam indicators")
            confidence -= 0.5
            
        # Date validation
        if start_time:
            try:
                from datetime import datetime
                event_date = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                now = datetime.now(event_date.tzinfo) if event_date.tzinfo else datetime.now()
                
                # Check if date is reasonable (not too far in past or future)
                days_diff = (event_date - now).days
                if days_diff < -365:
                    issues.append("Event date is more than a year in the past")
                    confidence -= 0.4
                elif days_diff > 365:
                    suggestions.append("Event is scheduled far in advance")
                    confidence -= 0.1
            except (ValueError, TypeError):
                issues.append("Invalid date format")
                confidence -= 0.2
        else:
            suggestions.append("Event is missing a start time")
            confidence -= 0.1
            
        # Location validation
        if not location:
            suggestions.append("Consider adding a location")
        elif len(location.strip()) < 5:
            suggestions.append("Location seems incomplete")
            
        # Description validation
        if not description:
            suggestions.append("Consider adding a description")
        elif len(description) < 20:
            suggestions.append("Description is brief - consider adding more detail")
            
        # Detect category from title/description
        category = "general"
        text_to_check = f"{title} {description or ''}".lower()
        
        category_keywords = {
            "meeting": ["meeting", "council", "board", "commission", "committee", "session"],
            "hearing": ["hearing", "public hearing", "zoning hearing"],
            "recreation": ["run", "walk", "race", "sports", "tournament", "game", "fitness"],
            "community": ["festival", "fair", "parade", "celebration", "holiday", "community"],
            "education": ["class", "workshop", "seminar", "training", "lecture", "education"],
            "health": ["health", "wellness", "medical", "clinic", "screening"],
        }
        
        for cat, keywords in category_keywords.items():
            if any(kw in text_to_check for kw in keywords):
                category = cat
                break
                
        is_valid = len(issues) == 0 and confidence >= 0.5
        
        return {
            "is_valid": is_valid,
            "confidence": max(0.0, min(1.0, confidence)),
            "issues": issues,
            "suggestions": suggestions,
            "category": category,
            "event_summary": {
                "title": title,
                "has_description": bool(description),
                "has_start_time": bool(start_time),
                "has_location": bool(location),
            }
        }
    
    @mcp.tool()
    async def find_duplicate_events(
        city_id: str,
        title: str,
        start_time: str | None = None,
    ) -> dict[str, Any]:
        """
        Find potential duplicate events in the database.
        
        Use this tool before creating a new event to check if it
        already exists. Returns events with similar titles or
        on the same date.
        
        Args:
            city_id: The city identifier
            title: The event title to check
            start_time: Optional ISO datetime to narrow search
            
        Returns:
            Dictionary containing:
            - has_duplicates: Boolean indicating if duplicates found
            - potential_matches: List of similar events
            - recommendation: String with suggested action
        """
        # Search for events with similar titles
        search_terms = title.lower().split()[:3]  # First 3 words
        search_query = " ".join(search_terms)
        
        existing_events = await db.search_events(
            city_id=city_id,
            query=search_query,
            limit=10,
        )
        
        potential_matches = []
        
        for event in existing_events:
            # Calculate title similarity (simple approach)
            event_title_lower = event["title"].lower()
            title_lower = title.lower()
            
            # Check for exact match
            if event_title_lower == title_lower:
                similarity = 1.0
            # Check if one contains the other
            elif title_lower in event_title_lower or event_title_lower in title_lower:
                similarity = 0.8
            # Check word overlap
            else:
                event_words = set(event_title_lower.split())
                title_words = set(title_lower.split())
                overlap = len(event_words & title_words)
                total = len(event_words | title_words)
                similarity = overlap / total if total > 0 else 0
                
            # Check date match if provided
            date_match = False
            if start_time and event.get("start_time"):
                try:
                    from datetime import datetime
                    new_date = datetime.fromisoformat(start_time.replace('Z', '+00:00')).date()
                    existing_date = event["start_time"].date() if hasattr(event["start_time"], 'date') else datetime.fromisoformat(str(event["start_time"])).date()
                    date_match = new_date == existing_date
                except (ValueError, TypeError):
                    pass
                    
            if similarity >= 0.5 or date_match:
                potential_matches.append({
                    "id": event["id"],
                    "title": event["title"],
                    "start_time": event["start_time"].isoformat() if event.get("start_time") else None,
                    "source": event.get("source_name"),
                    "similarity_score": similarity,
                    "same_date": date_match,
                })
                
        # Sort by similarity
        potential_matches.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        has_duplicates = any(m["similarity_score"] >= 0.8 for m in potential_matches)
        
        if has_duplicates:
            recommendation = "High-confidence duplicate found. Consider updating existing event instead of creating new."
        elif potential_matches:
            recommendation = "Some similar events found. Review to determine if this is a duplicate."
        else:
            recommendation = "No duplicates found. Safe to create new event."
            
        return {
            "has_duplicates": has_duplicates,
            "potential_matches": potential_matches[:5],  # Top 5
            "recommendation": recommendation,
        }
    
    @mcp.tool()
    async def enrich_event_data(
        title: str,
        description: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """
        Enrich event data with additional metadata.
        
        Use this tool to extract and infer additional information
        from event text, such as categories, accessibility info,
        registration requirements, and more.
        
        Args:
            title: The event title
            description: Optional event description
            location: Optional location/address
            
        Returns:
            Dictionary containing enriched data:
            - category: Primary event category
            - subcategory: More specific category
            - tags: List of relevant tags
            - is_recurring: Whether event appears recurring
            - accessibility: Accessibility indicators found
            - requires_registration: Whether registration seems required
            - is_free: Whether event appears to be free
            - target_audience: Detected target audience
        """
        text = f"{title} {description or ''} {location or ''}".lower()
        
        # Category detection
        category_map = {
            "government": ["council", "commission", "board", "zoning", "planning", "hearing", "ordinance"],
            "recreation": ["run", "walk", "race", "sports", "game", "tournament", "swim", "fitness", "park"],
            "community": ["festival", "fair", "parade", "celebration", "volunteer", "cleanup", "neighborhood"],
            "education": ["class", "workshop", "seminar", "training", "lecture", "learn", "education"],
            "health": ["health", "wellness", "medical", "clinic", "screening", "fitness", "yoga"],
            "arts": ["concert", "music", "art", "theater", "performance", "exhibit", "gallery"],
            "family": ["kids", "children", "family", "youth", "teen", "santa", "easter", "halloween"],
        }
        
        category = "general"
        for cat, keywords in category_map.items():
            if any(kw in text for kw in keywords):
                category = cat
                break
                
        # Subcategory detection
        subcategory_map = {
            "city_council_meeting": ["city council", "council meeting"],
            "planning_meeting": ["planning commission", "zoning board", "planning meeting"],
            "public_hearing": ["public hearing"],
            "5k_run": ["5k", "fun run"],
            "holiday_event": ["christmas", "holiday", "santa", "thanksgiving", "easter", "july 4", "memorial day"],
            "senior_event": ["senior", "seniors", "50+", "retirement"],
        }
        
        subcategory = None
        for subcat, keywords in subcategory_map.items():
            if any(kw in text for kw in keywords):
                subcategory = subcat
                break
                
        # Tag extraction
        tags = []
        tag_keywords = {
            "outdoor": ["outdoor", "park", "trail", "outside"],
            "indoor": ["indoor", "inside", "building", "hall", "center"],
            "free": ["free", "no cost", "no charge"],
            "family-friendly": ["family", "kids", "children", "all ages"],
            "seniors": ["senior", "seniors", "50+", "retirement"],
            "virtual": ["virtual", "online", "zoom", "webinar"],
            "food": ["food", "meal", "lunch", "dinner", "breakfast", "snack"],
        }
        
        for tag, keywords in tag_keywords.items():
            if any(kw in text for kw in keywords):
                tags.append(tag)
                
        # Recurring detection
        recurring_indicators = ["every", "weekly", "monthly", "annual", "recurring", "series"]
        is_recurring = any(indicator in text for indicator in recurring_indicators)
        
        # Accessibility detection
        accessibility = []
        accessibility_keywords = {
            "wheelchair_accessible": ["wheelchair", "accessible", "ada", "handicap"],
            "hearing_assistance": ["hearing loop", "sign language", "asl", "captioned"],
            "parking_available": ["parking", "garage"],
        }
        
        for access_type, keywords in accessibility_keywords.items():
            if any(kw in text for kw in keywords):
                accessibility.append(access_type)
                
        # Registration detection
        registration_keywords = ["register", "registration", "sign up", "rsvp", "ticket", "reserve"]
        requires_registration = any(kw in text for kw in registration_keywords)
        
        # Free event detection
        free_keywords = ["free", "no cost", "no charge", "complimentary", "open to public"]
        paid_keywords = ["ticket", "admission", "fee", "$", "cost"]
        is_free = any(kw in text for kw in free_keywords) and not any(kw in text for kw in paid_keywords)
        
        # Target audience
        target_audience = "general_public"
        audience_map = {
            "seniors": ["senior", "seniors", "50+", "retirement", "older adult"],
            "families": ["family", "families", "kids", "children", "all ages"],
            "teens": ["teen", "teens", "youth", "young adult"],
            "business": ["business", "entrepreneur", "chamber", "networking"],
        }
        
        for audience, keywords in audience_map.items():
            if any(kw in text for kw in keywords):
                target_audience = audience
                break
                
        return {
            "category": category,
            "subcategory": subcategory,
            "tags": tags,
            "is_recurring": is_recurring,
            "accessibility": accessibility,
            "requires_registration": requires_registration,
            "is_free": is_free if is_free else None,  # None if we can't determine
            "target_audience": target_audience,
        }



