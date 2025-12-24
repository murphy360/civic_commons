import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * GET /api/legislation
 * Returns legislation (ordinances/resolutions) with linking status and available events
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get('limit') || '50');
    const offset = parseInt(searchParams.get('offset') || '0');
    const filter = searchParams.get('filter') || 'all'; // all, linked, unlinked

    let whereClause = "WHERE document_type IN ('ordinance', 'resolution')";
    
    if (filter === 'linked') {
      whereClause += `
        AND EXISTS (
          SELECT 1 FROM legislation_mentions lm 
          WHERE lm.document_id = d.id AND lm.event_id IS NOT NULL
        )
      `;
    } else if (filter === 'unlinked') {
      whereClause += `
        AND NOT EXISTS (
          SELECT 1 FROM legislation_mentions lm 
          WHERE lm.document_id = d.id AND lm.event_id IS NOT NULL
        )
      `;
    }

    // Get legislation items
    const legislation = await sql`
      SELECT 
        d.id,
        d.title,
        d.source_name,
        d.document_type,
        d.legislation_number,
        d.legislation_year,
        d.legislation_status,
        d.proposed_date,
        d.published_date,
        d.updated_at,
        COUNT(DISTINCT lm.id) FILTER (WHERE lm.event_id IS NOT NULL)::int as linked_events_count,
        COUNT(DISTINCT lm.id)::int as total_mentions
      FROM documents d
      LEFT JOIN legislation_mentions lm ON d.id = lm.document_id
      ${sql.unsafe(whereClause)}
      GROUP BY d.id
      ORDER BY d.proposed_date DESC NULLS LAST, d.published_date DESC NULLS LAST
      LIMIT ${limit} OFFSET ${offset}
    `;

    // Get total count
    const countResult = await sql`
      SELECT COUNT(*) as total
      FROM documents d
      LEFT JOIN legislation_mentions lm ON d.id = lm.document_id
      ${sql.unsafe(whereClause)}
    `;
    const total = countResult[0]?.total || 0;

    return NextResponse.json({
      legislation: legislation || [],
      pagination: {
        limit,
        offset,
        total,
        hasMore: offset + limit < total
      }
    });
  } catch (error) {
    console.error('Failed to fetch legislation:', error);
    return NextResponse.json(
      { error: 'Failed to fetch legislation' },
      { status: 500 }
    );
  }
}

/**
 * POST /api/legislation/:id/link
 * Links a legislation document to events
 */
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { documentId, eventIds, action } = body;

    if (!documentId || !Array.isArray(eventIds) || !action) {
      return NextResponse.json(
        { error: 'Missing required fields: documentId, eventIds, action' },
        { status: 400 }
      );
    }

    if (action === 'link') {
      // Create/update legislation mentions with event links
      for (const eventId of eventIds) {
        await sql`
          INSERT INTO legislation_mentions (document_id, event_id, legislation_type, legislation_number, action_taken, mentioned_date)
          SELECT 
            ${documentId},
            ${eventId},
            CASE WHEN d.document_type = 'ordinance' THEN 'ordinance'::text ELSE 'resolution'::text END,
            COALESCE(d.legislation_number, ''),
            'discussed'::legislation_action,
            COALESCE(e.start_time, NOW())
          FROM documents d
          CROSS JOIN events e
          WHERE d.id = ${documentId} AND e.id = ${eventId}
          ON CONFLICT DO NOTHING
        `;
      }

      return NextResponse.json({
        success: true,
        message: `Linked ${eventIds.length} events`
      });
    } else if (action === 'unlink') {
      // Remove legislation mention links
      await sql`
        DELETE FROM legislation_mentions
        WHERE document_id = ${documentId} AND event_id = ANY($1::int[])
      `, [eventIds];

      return NextResponse.json({
        success: true,
        message: `Unlinked ${eventIds.length} events`
      });
    } else {
      return NextResponse.json(
        { error: 'Invalid action. Must be "link" or "unlink"' },
        { status: 400 }
      );
    }
  } catch (error) {
    console.error('Failed to update legislation links:', error);
    return NextResponse.json(
      { error: 'Failed to update legislation links' },
      { status: 500 }
    );
  }
}

/**
 * Helper function to get available events for linking to a specific legislation document
 * NOTE: Not exported - Next.js route handlers only allow GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS exports
 */
async function getAvailableEvents(legislationId: number) {
  try {
    const legislation = await sql`
      SELECT d.id, d.title, d.proposed_date, d.published_date, d.source_id
      FROM documents d
      WHERE d.id = ${legislationId}
    `;

    if (!legislation || legislation.length === 0) {
      return null;
    }

    const doc = legislation[0];
    const searchDate = doc.proposed_date || doc.published_date;

    // Find events by date proximity and source
    const events = await sql`
      SELECT 
        e.id,
        e.title,
        e.start_time,
        e.location,
        es.source_id,
        EXTRACT(DAY FROM (${searchDate}::date - e.start_time::date))::int as days_from_doc,
        EXISTS(
          SELECT 1 FROM legislation_mentions lm 
          WHERE lm.document_id = ${legislationId} AND lm.event_id = e.id
        ) as already_linked
      FROM events e
      LEFT JOIN event_sources es ON e.id = es.event_id
      WHERE ABS(EXTRACT(DAY FROM (${searchDate}::date - e.start_time::date))) <= 30
      ORDER BY days_from_doc ASC, e.start_time DESC
      LIMIT 50
    `;

    return events || [];
  } catch (error) {
    console.error('Failed to fetch available events:', error);
    return null;
  }
}
