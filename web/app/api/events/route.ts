import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const events = await sql`
      SELECT 
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.location,
        (SELECT es2.source_url FROM event_sources es2 WHERE es2.event_id = e.id ORDER BY es2.first_seen_at LIMIT 1) as source_url,
        e.video_url,
        COALESCE(string_agg(DISTINCT s.name, ', ' ORDER BY s.name), 'Unknown') as source_names,
        COUNT(DISTINCT es.source_id)::int as source_count,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id) as document_count,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'agenda') as has_agenda,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'minutes') as has_minutes
      FROM events e
      LEFT JOIN event_sources es ON e.id = es.event_id
      LEFT JOIN sources s ON es.source_id = s.id
      GROUP BY e.id
      ORDER BY e.start_time ASC
      LIMIT 50
    `;

    return NextResponse.json({ events });
  } catch (error) {
    console.error('Failed to fetch events:', error);
    return NextResponse.json(
      { error: 'Failed to fetch events' },
      { status: 500 }
    );
  }
}
