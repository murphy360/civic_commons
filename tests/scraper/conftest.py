"""
Pytest configuration and fixtures for scraper tests.
"""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def mock_html_response() -> str:
    """Sample HTML response for testing parsers."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>City Council</title></head>
    <body>
        <div class="meeting-list">
            <div class="meeting-item">
                <h3>City Council Regular Meeting</h3>
                <span class="date">January 15, 2024</span>
                <span class="time">7:00 PM</span>
                <span class="location">City Hall</span>
            </div>
        </div>
    </body>
    </html>
    """


@pytest_asyncio.fixture
async def mock_rss_response() -> str:
    """Sample RSS feed for testing RSS driver."""
    return """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>Library Events</title>
            <item>
                <title>Book Club Meeting</title>
                <description>Monthly book discussion</description>
                <pubDate>Mon, 15 Jan 2024 19:00:00 EST</pubDate>
                <link>https://library.example.com/events/1</link>
            </item>
        </channel>
    </rss>
    """


@pytest.fixture
def sample_source_config() -> dict:
    """Sample source configuration for testing."""
    return {
        "name": "Test City Council",
        "source_type": "city_council",
        "driver": "civic_plus",
        "url": "https://example.com/meetings",
        "selectors": {
            "event_list": ".meeting-list .meeting-item",
            "title": "h3",
            "date": ".date",
            "time": ".time",
            "location": ".location",
        },
    }
