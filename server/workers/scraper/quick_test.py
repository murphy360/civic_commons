#!/usr/bin/env python3
"""Quick test to verify RSS driver works with all agendas"""

import asyncio
from drivers import get_driver
from config import SourceConfig, CityConfig, CityProfile

config = CityConfig(
    city_profile=CityProfile(name='Twinsburg, OH', zip='44087', timezone='America/New_York'),
    sources=[]
)

source = SourceConfig(
    name='All Agendas RSS',
    driver='civic_plus_rss',
    schedule='0 * * * *',
    params={
        'base_url': 'https://www.mytwinsburg.com',
        'module': 'agenda',
        'categories': ['all'],
    }
)

async def test():
    driver = get_driver('civic_plus_rss')(source_config=source, city_config=config)
    events, docs = await driver.fetch()
    print(f'Found {len(events)} meetings from RSS feed')
    print('\nRecent meetings:')
    for e in sorted(events, key=lambda x: x.starts_at, reverse=True)[:20]:
        date_str = e.starts_at.strftime('%Y-%m-%d') if e.starts_at else 'No date'
        print(f'  {date_str}: {e.title}')

if __name__ == '__main__':
    asyncio.run(test())

