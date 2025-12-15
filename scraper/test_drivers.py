#!/usr/bin/env python3
"""
Purpose: Test script to verify scraper drivers work correctly
Usage: python test_drivers.py [driver_name]
Dependencies: httpx, feedparser, beautifulsoup4

This script tests the scraper drivers against live data sources.
Run from the scraper directory: cd scraper && python test_drivers.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from drivers import get_driver, DRIVER_REGISTRY
from config import SourceConfig, CityConfig, CityProfile


def create_test_config() -> CityConfig:
    """Create a test city configuration."""
    return CityConfig(
        city_profile=CityProfile(
            name="Twinsburg, OH",
            zip="44087",
            timezone="America/New_York",
        ),
        sources=[],
    )


async def test_civic_plus_rss():
    """Test the CivicPlus RSS driver."""
    print("\n" + "="*60)
    print("Testing CivicPlusRssDriver")
    print("="*60)
    
    config = create_test_config()
    source = SourceConfig(
        name="Test City Council RSS",
        driver="civic_plus_rss",
        schedule="0 * * * *",
        params={
            "base_url": "https://www.mytwinsburg.com",
            "module": "agenda",
            "categories": ["city_council"],
        },
    )
    
    driver_class = get_driver("civic_plus_rss")
    driver = driver_class(source_config=source, city_config=config)
    
    print(f"Fetching from: {source.params['base_url']}")
    print(f"Module: {source.params['module']}")
    print(f"Categories: {source.params['categories']}")
    
    try:
        events, documents = await driver.fetch()
        
        print(f"\n✅ Found {len(events)} events, {len(documents)} documents")
        
        if events:
            print("\nSample events:")
            for event in events[:5]:
                print(f"  - {event.starts_at.strftime('%Y-%m-%d') if event.starts_at else 'No date'}: {event.title}")
        
        if documents:
            print("\nSample documents:")
            for doc in documents[:5]:
                print(f"  - [{doc.doc_type.value}] {doc.title[:50]}...")
                
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


async def test_civic_plus_calendar():
    """Test the CivicPlus Calendar driver."""
    print("\n" + "="*60)
    print("Testing CivicPlusCalendarDriver")
    print("="*60)
    
    config = create_test_config()
    source = SourceConfig(
        name="Test Parks & Rec",
        driver="civic_plus_calendar",
        schedule="0 * * * *",
        params={
            "base_url": "https://www.mytwinsburg.com",
            "calendar_ids": [22],  # Parks & Recreation
            "days_ahead": 30,
        },
    )
    
    driver_class = get_driver("civic_plus_calendar")
    driver = driver_class(source_config=source, city_config=config)
    
    print(f"Fetching from: {source.params['base_url']}/Calendar.aspx")
    print(f"Calendar IDs: {source.params['calendar_ids']}")
    
    try:
        events, documents = await driver.fetch()
        
        print(f"\n✅ Found {len(events)} events")
        
        if events:
            print("\nSample events:")
            for event in events[:5]:
                date_str = event.starts_at.strftime('%Y-%m-%d %H:%M') if event.starts_at else 'No date'
                loc = f" @ {event.location}" if event.location else ""
                print(f"  - {date_str}: {event.title}{loc}")
                
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


async def test_civic_plus_agenda():
    """Test the CivicPlus Agenda Center driver (HTML scraping)."""
    print("\n" + "="*60)
    print("Testing CivicPlusDriver (HTML scraping)")
    print("="*60)
    
    config = create_test_config()
    source = SourceConfig(
        name="Test Agenda Center",
        driver="civic_plus",
        schedule="0 * * * *",
        params={
            "base_url": "https://www.mytwinsburg.com",
            "categories": ["City Council"],
        },
    )
    
    driver_class = get_driver("civic_plus")
    driver = driver_class(source_config=source, city_config=config)
    
    print(f"Fetching from: {source.params['base_url']}/AgendaCenter")
    print(f"Categories: {source.params['categories']}")
    
    try:
        events, documents = await driver.fetch()
        
        print(f"\n✅ Found {len(events)} events, {len(documents)} documents")
        
        if events:
            print("\nSample events:")
            for event in events[:5]:
                date_str = event.starts_at.strftime('%Y-%m-%d') if event.starts_at else 'No date'
                print(f"  - {date_str}: {event.title}")
        
        if documents:
            print("\nSample documents:")
            for doc in documents[:5]:
                print(f"  - [{doc.doc_type.value}] {doc.title[:60]}...")
                
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


async def test_generic_rss():
    """Test the generic RSS driver."""
    print("\n" + "="*60)
    print("Testing RssDriver (Generic)")
    print("="*60)
    
    config = create_test_config()
    source = SourceConfig(
        name="Test Calendar RSS",
        driver="rss",
        schedule="0 * * * *",
        params={
            "feed_url": "https://www.mytwinsburg.com/RSSFeed.aspx?ModID=58&CID=Main-Calendar-14",
        },
    )
    
    driver_class = get_driver("rss")
    driver = driver_class(source_config=source, city_config=config)
    
    print(f"Fetching from: {source.params['feed_url']}")
    
    try:
        events, documents = await driver.fetch()
        
        print(f"\n✅ Found {len(events)} events")
        
        if events:
            print("\nSample events:")
            for event in events[:5]:
                date_str = event.starts_at.strftime('%Y-%m-%d') if event.starts_at else 'No date'
                print(f"  - {date_str}: {event.title[:60]}")
                
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise


async def main():
    """Run all driver tests."""
    print("="*60)
    print("CIVIC COMMONS - Driver Test Suite")
    print("="*60)
    print(f"\nRegistered drivers: {list(DRIVER_REGISTRY.keys())}")
    
    # Get specific driver to test from command line
    driver_to_test = sys.argv[1] if len(sys.argv) > 1 else None
    
    tests = [
        ("civic_plus_rss", test_civic_plus_rss),
        ("civic_plus_calendar", test_civic_plus_calendar),
        ("civic_plus", test_civic_plus_agenda),
        ("rss", test_generic_rss),
    ]
    
    for driver_name, test_func in tests:
        if driver_to_test and driver_to_test != driver_name:
            continue
            
        try:
            await test_func()
        except Exception as e:
            print(f"\n❌ Test failed for {driver_name}: {e}")
    
    print("\n" + "="*60)
    print("Tests complete!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
