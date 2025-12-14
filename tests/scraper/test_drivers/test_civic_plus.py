"""
Tests for the CivicPlus driver.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestCivicPlusDriver:
    """Tests for CivicPlusDriver."""
    
    @pytest.mark.asyncio
    async def test_driver_initialization(self, sample_source_config):
        """Test driver can be initialized with config."""
        from scraper.drivers.civic_plus import CivicPlusDriver
        
        driver = CivicPlusDriver(sample_source_config)
        assert driver.config == sample_source_config
        assert driver.name == "Test City Council"
    
    @pytest.mark.asyncio
    async def test_parse_meeting_page(self, mock_html_response):
        """Test parsing a meeting listing page."""
        from scraper.drivers.civic_plus import CivicPlusDriver
        
        config = {
            "name": "Test",
            "url": "https://example.com",
            "selectors": {
                "event_list": ".meeting-item",
                "title": "h3",
                "date": ".date",
            },
        }
        driver = CivicPlusDriver(config)
        
        # Mock the HTTP response
        with patch.object(driver, '_fetch_page', return_value=mock_html_response):
            result = await driver.fetch()
            
            assert result.success
            assert len(result.events) >= 1
            assert result.events[0].title == "City Council Regular Meeting"
    
    @pytest.mark.asyncio
    async def test_handles_empty_page(self):
        """Test driver handles empty pages gracefully."""
        from scraper.drivers.civic_plus import CivicPlusDriver
        
        config = {"name": "Test", "url": "https://example.com"}
        driver = CivicPlusDriver(config)
        
        with patch.object(driver, '_fetch_page', return_value="<html></html>"):
            result = await driver.fetch()
            
            assert result.success
            assert len(result.events) == 0
    
    @pytest.mark.asyncio
    async def test_handles_network_error(self):
        """Test driver handles network errors."""
        from scraper.drivers.civic_plus import CivicPlusDriver
        
        config = {"name": "Test", "url": "https://example.com"}
        driver = CivicPlusDriver(config)
        
        with patch.object(driver, '_fetch_page', side_effect=Exception("Network error")):
            result = await driver.fetch()
            
            assert not result.success
            assert "Network error" in result.error
