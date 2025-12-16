import { NextRequest, NextResponse } from 'next/server';
import { sql } from '@/lib/db';

interface Event {
  id: number;
  title: string;
  description: string | null;
  start_time: Date;
  end_time: Date | null;
  location: string | null;
  source_url: string | null;
  video_url: string | null;
  source_names: string;
  source_count: number;
  document_count: number;
  has_agenda: number;
  has_minutes: number;
  first_doc_id: number | null;
  has_ai_summary: boolean;
}

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const offset = parseInt(searchParams.get('offset') || '0', 10);
  const limit = Math.min(parseInt(searchParams.get('limit') || '50', 10), 100);

  try {
    // Get total count
    const countResult = await sql<{ count: number }[]>`
      SELECT COUNT(*)::int as count 
      FROM events 
      WHERE start_time < NOW() - INTERVAL '1 day'
    `;
    const total = countResult[0]?.count || 0;

    // Get paginated events
    const events = await sql<Event[]>`
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
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id)::int as document_count,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'agenda')::int as has_agenda,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'minutes')::int as has_minutes,
        (SELECT ed.document_id FROM event_documents ed WHERE ed.event_id = e.id ORDER BY 
          CASE ed.relationship WHEN 'agenda' THEN 1 WHEN 'minutes' THEN 2 ELSE 3 END LIMIT 1)::int as first_doc_id,
        (e.ai_summary IS NOT NULL) as has_ai_summary
      FROM events e
      LEFT JOIN event_sources es ON e.id = es.event_id
      LEFT JOIN sources s ON es.source_id = s.id
      WHERE e.start_time < NOW() - INTERVAL '1 day'
      GROUP BY e.id
      ORDER BY e.start_time DESC
      LIMIT ${limit}
      OFFSET ${offset}
    `;

    return NextResponse.json({
      events,
      total,
      offset,
      limit,
      hasMore: offset + events.length < total,
    });
  } catch (error) {
    console.error('Failed to fetch past events:', error);
    return NextResponse.json(
      { error: 'Failed to fetch events' },
      { status: 500 }
    );
  }
}
