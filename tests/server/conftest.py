"""
Pytest configuration and fixtures for MCP server tests.
"""

import asyncio
from typing import Generator

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db():
    """Mock database for testing."""
    from unittest.mock import AsyncMock
    
    db = AsyncMock()
    
    # Mock events query
    db.get_events.return_value = [
        {
            "id": 1,
            "title": "City Council Meeting",
            "description": "Regular monthly meeting",
            "start_time": "2024-01-15T19:00:00",
            "end_time": "2024-01-15T21:00:00",
            "location": "City Hall",
            "source_name": "City Council",
            "source_url": "https://example.com/meeting/1",
        }
    ]
    
    # Mock documents search
    db.search_documents.return_value = [
        {
            "id": 1,
            "title": "City Council Minutes - January 2024",
            "document_type": "minutes",
            "published_date": "2024-01-16",
            "source_name": "City Council",
            "source_url": "https://example.com/doc/1",
            "rank": 0.95,
        }
    ]
    
    # Mock assistant config
    db.get_assistant_config.return_value = {
        "city_id": "twinsburg",
        "display_name": "Twinsburg, Ohio",
        "assistant_name": "TwinBot",
        "assistant_persona": "A helpful community assistant",
        "timezone": "America/New_York",
    }
    
    # Mock source health
    db.get_source_health.return_value = [
        {
            "id": 1,
            "name": "City Council",
            "source_type": "city_council",
            "health_status": "healthy",
            "last_success_at": "2024-01-15T10:00:00",
            "last_error": None,
            "is_enabled": True,
        }
    ]
    
    return db
