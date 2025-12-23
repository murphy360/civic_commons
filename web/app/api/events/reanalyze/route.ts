import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  try {
    const { eventId } = await request.json();

    if (!eventId || typeof eventId !== 'number') {
      return NextResponse.json(
        { error: 'Invalid eventId' },
        { status: 400 }
      );
    }

    // Check if event exists
    const event = await sql`
      SELECT id FROM events WHERE id = ${eventId}
    `;

    if (!event || event.length === 0) {
      return NextResponse.json(
        { error: 'Event not found' },
        { status: 404 }
      );
    }

    // Clear AI summary to trigger re-analysis
    // The worker will regenerate the summary when it processes pending summaries
    await sql`
      UPDATE events 
      SET ai_summary = NULL,
          ai_summary_updated_at = NULL
      WHERE id = ${eventId}
    `;

    return NextResponse.json({
      success: true,
      message: 'Event queued for re-analysis',
      eventId,
    });
  } catch (error) {
    console.error('Failed to reanalyze event:', error);
    return NextResponse.json(
      { error: 'Failed to queue event for re-analysis' },
      { status: 500 }
    );
  }
}
