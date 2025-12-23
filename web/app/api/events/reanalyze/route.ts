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
    // Set summary_priority to NOW() to prioritize manually queued items
    // The worker will regenerate the summary when it processes pending summaries
    await sql`
      UPDATE events 
      SET ai_summary = NULL,
          ai_summary_updated_at = NULL,
          summary_priority = NOW()
      WHERE id = ${eventId}
    `;

    // Also prioritize all linked documents so they get processed first
    // This ensures the event can be summarized once its documents are ready
    // Note: We don't clear existing summaries - only prioritize pending ones
    const docsUpdated = await sql`
      UPDATE documents 
      SET summary_priority = NOW(),
          content_status = CASE 
            WHEN ai_summary IS NULL AND content_status NOT IN ('ai_pending', 'extracting', 'downloading') 
            THEN 'ai_pending' 
            ELSE content_status 
          END
      FROM event_documents ed
      WHERE documents.id = ed.document_id
        AND ed.event_id = ${eventId}
      RETURNING documents.id
    `;

    return NextResponse.json({
      success: true,
      message: `Event and ${docsUpdated.length} linked documents queued for re-analysis`,
      eventId,
      documentsQueued: docsUpdated.length,
    });
  } catch (error) {
    console.error('Failed to reanalyze event:', error);
    return NextResponse.json(
      { error: 'Failed to queue event for re-analysis' },
      { status: 500 }
    );
  }
}
