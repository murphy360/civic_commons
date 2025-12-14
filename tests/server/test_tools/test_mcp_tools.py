"""
Tests for MCP tools.
"""

import pytest
from datetime import date


class TestGetCommonsCalendar:
    """Tests for get_commons_calendar tool."""
    
    @pytest.mark.asyncio
    async def test_returns_events(self, mock_db):
        """Test that calendar returns events."""
        from server.tools import register_tools
        from unittest.mock import MagicMock
        
        mcp = MagicMock()
        registered_tools = {}
        
        def capture_tool():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator
        
        mcp.tool = capture_tool
        register_tools(mcp, mock_db)
        
        result = await registered_tools['get_commons_calendar'](
            city_id="twinsburg",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        
        assert result['city_id'] == "twinsburg"
        assert result['total_count'] >= 1
        assert result['events'][0]['title'] == "City Council Meeting"
    
    @pytest.mark.asyncio
    async def test_default_date_range(self, mock_db):
        """Test that default date range is applied."""
        from server.tools import register_tools
        from unittest.mock import MagicMock
        
        mcp = MagicMock()
        registered_tools = {}
        
        def capture_tool():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator
        
        mcp.tool = capture_tool
        register_tools(mcp, mock_db)
        
        result = await registered_tools['get_commons_calendar'](city_id="twinsburg")
        
        # Should default to today + 30 days
        assert 'date_range' in result
        assert 'start' in result['date_range']
        assert 'end' in result['date_range']


class TestSearchCommonsRecords:
    """Tests for search_commons_records tool."""
    
    @pytest.mark.asyncio
    async def test_search_returns_results(self, mock_db):
        """Test that search returns matching documents."""
        from server.tools import register_tools
        from unittest.mock import MagicMock
        
        mcp = MagicMock()
        registered_tools = {}
        
        def capture_tool():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator
        
        mcp.tool = capture_tool
        register_tools(mcp, mock_db)
        
        result = await registered_tools['search_commons_records'](
            city_id="twinsburg",
            query="city council minutes",
        )
        
        assert result['city_id'] == "twinsburg"
        assert result['query'] == "city council minutes"
        assert result['total_count'] >= 1


class TestGetAssistantManifest:
    """Tests for get_assistant_manifest tool."""
    
    @pytest.mark.asyncio
    async def test_returns_config(self, mock_db):
        """Test that manifest returns assistant config."""
        from server.tools import register_tools
        from unittest.mock import MagicMock
        
        mcp = MagicMock()
        registered_tools = {}
        
        def capture_tool():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator
        
        mcp.tool = capture_tool
        register_tools(mcp, mock_db)
        
        result = await registered_tools['get_assistant_manifest'](city_id="twinsburg")
        
        assert result['city_id'] == "twinsburg"
        assert result['assistant']['name'] == "TwinBot"
