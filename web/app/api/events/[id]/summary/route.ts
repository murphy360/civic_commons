import { NextRequest, NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

// GET /api/events/[id]/summary - Get existing summary
export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  const eventId = parseInt(params.id);
  
  if (isNaN(eventId)) {
    return NextResponse.json({ error: 'Invalid event ID' }, { status: 400 });
  }

  try {
    const events = await sql<Array<{
      ai_summary: string | null;
      ai_summary_updated_at: Date | null;
    }>>`
      SELECT ai_summary, ai_summary_updated_at
      FROM events
      WHERE id = ${eventId}
    `;

    if (events.length === 0) {
      return NextResponse.json({ error: 'Event not found' }, { status: 404 });
    }

    return NextResponse.json({
      summary: events[0].ai_summary,
      updatedAt: events[0].ai_summary_updated_at,
    });
  } catch (error) {
    console.error('Failed to fetch event summary:', error);
    return NextResponse.json(
      { error: 'Failed to fetch summary' },
      { status: 500 }
    );
  }
}
