import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

interface EventDocument {
  id: number;
  title: string;
  document_type: string;
  relationship: string;
  source_url: string | null;
}

export async function GET(
  request: Request,
  { params }: { params: { id: string } }
) {
  try {
    const eventId = parseInt(params.id);
    
    if (isNaN(eventId)) {
      return NextResponse.json(
        { error: 'Invalid event ID' },
        { status: 400 }
      );
    }

    // Get event details
    const events = await sql<any[]>`
      SELECT 
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.location,
        e.source_url,
        e.video_url,
        s.name as source_name
      FROM events e
      JOIN sources s ON e.source_id = s.id
      WHERE e.id = ${eventId}
    `;

    if (events.length === 0) {
      return NextResponse.json(
        { error: 'Event not found' },
        { status: 404 }
      );
    }

    // Get associated documents
    const documents = await sql<EventDocument[]>`
      SELECT 
        d.id,
        d.title,
        d.document_type,
        ed.relationship,
        d.source_url
      FROM event_documents ed
      JOIN documents d ON ed.document_id = d.id
      WHERE ed.event_id = ${eventId}
      ORDER BY 
        CASE ed.relationship 
          WHEN 'agenda' THEN 1 
          WHEN 'minutes' THEN 2 
          WHEN 'packet' THEN 3
          ELSE 4 
        END
    `;

    return NextResponse.json({
      event: events[0],
      documents
    });
  } catch (error) {
    console.error('Failed to fetch event:', error);
    return NextResponse.json(
      { error: 'Failed to fetch event' },
      { status: 500 }
    );
  }
}
