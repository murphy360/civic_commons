#!/usr/bin/env python3
"""Test AI linking for Planning Commission agenda."""

import asyncio
import asyncpg
import os
import sys

sys.path.insert(0, '/app')

from pipeline.ai_processor import AIEventProcessor


async def test():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
    ai = AIEventProcessor(api_key=api_key)
    
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    
    async with pool.acquire() as conn:
        # Get Planning Commission events
        events = await conn.fetch("""
            SELECT id, title, start_time, description
            FROM events
            WHERE title ILIKE '%planning%commission%'
            ORDER BY start_time
        """)
        
        events_list = [
            {
                'id': e['id'],
                'title': e['title'],
                'start_time': e['start_time'].isoformat() if e['start_time'] else 'Unknown',
                'description': e['description']
            }
            for e in events
        ]
        
        print("Events for matching:")
        for e in events_list:
            print(f"  - Event {e['id']}: {e['title']} on {e['start_time']}")
        
        print("\n" + "="*60)
        print("Testing: Planning Commission Agenda")
        print("="*60)
        
        # Test with the agenda document
        matches = await ai.find_related_events(
            document_title="Planning Commission Agenda Meeting - Agenda",
            document_content=None,  # Let it read the PDF
            events=events_list,
            document_type="agenda",
            local_path="planning-zoning/Planning-Commission-Agenda-Meeting-Agenda_3e4f991b.pdf",
        )
        
        print(f"\nMatches found: {len(matches)}")
        for m in matches:
            event = next((e for e in events_list if e['id'] == m['event_id']), None)
            if event:
                print(f"  - Event {m['event_id']}: {event['title']} on {event['start_time']} ({m['relationship']})")
    
    await ai.close()
    await pool.close()


asyncio.run(test())
