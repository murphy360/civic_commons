"""
Tests for the RSS driver.
"""

import pytest
from unittest.mock import patch


class TestRssDriver:
    """Tests for RssDriver."""
    
    @pytest.mark.asyncio
    async def test_parse_rss_feed(self, mock_rss_response):
        """Test parsing an RSS feed."""
        from scraper.drivers.rss import RssDriver
        
        config = {
            "name": "Library Events",
            "url": "https://library.example.com/events.rss",
        }
        driver = RssDriver(config)
        
        with patch.object(driver, '_fetch_feed', return_value=mock_rss_response):
            result = await driver.fetch()
            
            assert result.success
            assert len(result.events) >= 1
            assert result.events[0].title == "Book Club Meeting"
    
    @pytest.mark.asyncio
    async def test_handles_invalid_rss(self):
        """Test driver handles invalid RSS gracefully."""
        from scraper.drivers.rss import RssDriver
        
        config = {"name": "Test", "url": "https://example.com/feed"}
        driver = RssDriver(config)
        
        with patch.object(driver, '_fetch_feed', return_value="not valid xml"):
            result = await driver.fetch()
            
            # Should handle gracefully, either success with 0 events or error
            assert isinstance(result.events, list)
