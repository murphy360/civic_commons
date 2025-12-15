#!/usr/bin/env python3
"""
Use AI to intelligently link documents to related events.

This script acts as an AI secretary that reviews unlinked documents
and finds matching events based on title similarity, content analysis,
and contextual understanding.
"""

import asyncio
import asyncpg
import os
import sys
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, '/app')

from pipeline.ai_processor import AIEventProcessor


async def get_unlinked_documents(conn) -> list[dict]:
    """Get documents that have no event associations."""
    docs = await conn.fetch("""
        SELECT d.id, d.title, d.content_text, d.document_type, d.published_date, d.local_path
        FROM documents d
        LEFT JOIN event_documents ed ON d.id = ed.document_id
        WHERE ed.document_id IS NULL
        ORDER BY d.created_at DESC
    """)
    return [dict(d) for d in docs]


async def get_upcoming_events(conn, days_ahead: int = 90) -> list[dict]:
    """Get events in the next N days for matching."""
    cutoff = datetime.now() + timedelta(days=days_ahead)
    events = await conn.fetch("""
        SELECT id, title, start_time, description
        FROM events
        WHERE start_time >= NOW() - INTERVAL '7 days'
          AND start_time <= $1
        ORDER BY start_time
    """, cutoff)
    return [
        {
            'id': e['id'],
            'title': e['title'],
            'start_time': e['start_time'].isoformat() if e['start_time'] else 'Unknown',
            'description': e['description']
        }
        for e in events
    ]


async def link_document_to_events(conn, document_id: int, matches: list[dict]) -> int:
    """Create event_documents links for the matches."""
    linked = 0
    for match in matches:
        try:
            await conn.execute("""
                INSERT INTO event_documents (event_id, document_id, relationship)
                VALUES ($1, $2, $3)
                ON CONFLICT (event_id, document_id) DO NOTHING
            """, match['event_id'], document_id, match.get('relationship', 'attachment'))
            linked += 1
        except Exception as e:
            print(f"  Error linking to event {match['event_id']}: {e}")
    return linked


async def main():
    print("=" * 60)
    print("AI Document-Event Linking")
    print("=" * 60)
    
    # Check for API key
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_AI_API_KEY")
    if not api_key:
        print("ERROR: No GEMINI_API_KEY or GOOGLE_AI_API_KEY found in environment")
        return
    
    # Initialize AI processor
    ai = AIEventProcessor(api_key=api_key)
    print(f"AI processor initialized (enabled: {ai.enabled})")
    
    # Connect to database
    db_url = os.environ['DATABASE_URL']
    pool = await asyncpg.create_pool(db_url)
    
    async with pool.acquire() as conn:
        # Get unlinked documents
        documents = await get_unlinked_documents(conn)
        print(f"\nFound {len(documents)} unlinked documents")
        
        if not documents:
            print("No unlinked documents to process")
            return
        
        # Get upcoming events for matching
        events = await get_upcoming_events(conn)
        print(f"Found {len(events)} upcoming events for matching\n")
        
        if not events:
            print("No upcoming events to match against")
            return
        
        # Process each unlinked document
        total_linked = 0
        for doc in documents:
            print(f"\nProcessing: {doc['title']}")
            print(f"  Type: {doc['document_type'] or 'unknown'}")
            if doc.get('published_date'):
                print(f"  Date: {doc['published_date']}")
            
            # Format document date for AI
            doc_date = None
            if doc.get('published_date'):
                doc_date = doc['published_date'].strftime('%Y-%m-%d') if hasattr(doc['published_date'], 'strftime') else str(doc['published_date'])
            
            # Use AI to find related events
            matches = await ai.find_related_events(
                document_title=doc['title'],
                document_content=doc.get('content_text'),
                events=events,
                document_date=doc_date,
                document_type=doc.get('document_type'),
                local_path=doc.get('local_path'),
            )
            
            if matches:
                print(f"  AI found {len(matches)} matching events:")
                for match in matches:
                    event = next((e for e in events if e['id'] == match['event_id']), None)
                    if event:
                        print(f"    - Event {match['event_id']}: {event['title']} ({match['relationship']})")
                
                # Create the links
                linked = await link_document_to_events(conn, doc['id'], matches)
                total_linked += linked
                print(f"  Created {linked} links")
            else:
                print(f"  No matching events found")
        
        print(f"\n{'=' * 60}")
        print(f"Summary: Created {total_linked} document-event links")
        print("=" * 60)
    
    await ai.close()
    await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
