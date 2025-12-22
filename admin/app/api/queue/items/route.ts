import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * GET /api/queue/items
 * Returns paginated queue items with optional filtering.
 * Query params:
 *   - status: Filter by content_status (discovered, downloading, etc.)
 *   - type: Filter by content type (document, video)
 *   - limit: Number of items (default 50)
 *   - offset: Pagination offset (default 0)
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const status = searchParams.get('status');
    const type = searchParams.get('type');
    const limit = Math.min(parseInt(searchParams.get('limit') || '50', 10), 100);
    const offset = parseInt(searchParams.get('offset') || '0', 10);

    // Build dynamic query
    let conditions: string[] = ['1=1'];
    
    if (status) {
      // Validate status to prevent SQL injection
      const validStatuses = [
        'discovered', 'download_pending', 'downloading', 'downloaded',
        'extraction_pending', 'extracting', 'extracted',
        'ai_pending', 'ai_processing', 'complete', 'failed', 'skipped'
      ];
      if (validStatuses.includes(status)) {
        conditions.push(`d.content_status = '${status}'`);
      }
    }

    if (type === 'video') {
      conditions.push(`d.document_type = 'video'`);
    } else if (type === 'document') {
      conditions.push(`(d.document_type != 'video' OR d.document_type IS NULL)`);
    }

    const whereClause = conditions.join(' AND ');

    // Get items
    const items = await sql.unsafe(`
      SELECT 
        d.id,
        d.title,
        d.document_type,
        d.content_status,
        d.source_url,
        d.local_path,
        d.meeting_date,
        d.error_message,
        d.retry_count,
        d.file_size_bytes,
        d.discovered_at,
        d.download_started_at,
        d.download_completed_at,
        d.extraction_started_at,
        d.extraction_completed_at,
        d.ai_started_at,
        d.ai_completed_at,
        d.created_at,
        d.updated_at,
        s.name as source_name,
        s.city_id
      FROM documents d
      JOIN sources s ON d.source_id = s.id
      WHERE ${whereClause}
      ORDER BY 
        CASE d.content_status
          WHEN 'downloading' THEN 1
          WHEN 'extracting' THEN 2
          WHEN 'ai_processing' THEN 3
          WHEN 'discovered' THEN 4
          WHEN 'download_pending' THEN 5
          WHEN 'extraction_pending' THEN 6
          WHEN 'ai_pending' THEN 7
          WHEN 'failed' THEN 8
          ELSE 9
        END,
        d.meeting_date DESC NULLS LAST,
        d.created_at DESC
      LIMIT ${limit} OFFSET ${offset}
    `);

    // Get total count for pagination
    const countResult = await sql.unsafe(`
      SELECT COUNT(*)::int as total
      FROM documents d
      WHERE ${whereClause}
    `);

    return NextResponse.json({
      items,
      pagination: {
        limit,
        offset,
        total: countResult[0]?.total || 0,
        hasMore: offset + items.length < (countResult[0]?.total || 0),
      },
    });
  } catch (error) {
    console.error('Queue items error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch queue items' },
      { status: 500 }
    );
  }
}

/**
 * POST /api/queue/items
 * Retry failed items or reset stuck items.
 * Body:
 *   - action: 'retry_failed' | 'reset_stuck' | 'skip'
 *   - ids: Array of document IDs (optional, applies to all if not specified)
 *   - max_retries: Max retry count for retry_failed (default 3)
 */
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { action, ids, max_retries = 3 } = body;

    let result: { affected: number; message: string };

    switch (action) {
      case 'retry_failed': {
        // Reset failed items for retry
        let query = `
          UPDATE documents
          SET 
            content_status = CASE
              WHEN local_path IS NOT NULL AND content_markdown IS NULL THEN 'extraction_pending'
              WHEN local_path IS NOT NULL THEN 'ai_pending'
              ELSE 'download_pending'
            END,
            error_message = NULL,
            updated_at = NOW()
          WHERE content_status = 'failed'
            AND retry_count < $1
        `;
        
        if (ids && ids.length > 0) {
          query += ` AND id = ANY($2)`;
          const res = await sql.unsafe(query + ' RETURNING id', [max_retries, ids]);
          result = { affected: res.length, message: `Reset ${res.length} failed items for retry` };
        } else {
          query += ' RETURNING id';
          const res = await sql.unsafe(query, [max_retries]);
          result = { affected: res.length, message: `Reset ${res.length} failed items for retry` };
        }
        break;
      }

      case 'reset_stuck': {
        // Reset items stuck in processing state
        const timeoutMinutes = 30;
        const res = await sql`
          UPDATE documents
          SET 
            content_status = CASE content_status
              WHEN 'downloading' THEN 'download_pending'
              WHEN 'extracting' THEN 'extraction_pending'
              WHEN 'ai_processing' THEN 'ai_pending'
              ELSE content_status
            END,
            error_message = 'Reset: processing timed out',
            updated_at = NOW()
          WHERE content_status IN ('downloading', 'extracting', 'ai_processing')
            AND updated_at < NOW() - INTERVAL '1 minute' * ${timeoutMinutes}
          RETURNING id
        `;
        result = { affected: res.length, message: `Reset ${res.length} stuck items` };
        break;
      }

      case 'skip': {
        // Mark items as skipped
        if (!ids || ids.length === 0) {
          return NextResponse.json({ error: 'IDs required for skip action' }, { status: 400 });
        }
        const res = await sql`
          UPDATE documents
          SET content_status = 'skipped', error_message = 'Manually skipped', updated_at = NOW()
          WHERE id = ANY(${ids})
          RETURNING id
        `;
        result = { affected: res.length, message: `Skipped ${res.length} items` };
        break;
      }

      default:
        return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
    }

    return NextResponse.json(result);
  } catch (error) {
    console.error('Queue action error:', error);
    return NextResponse.json(
      { error: 'Failed to perform queue action' },
      { status: 500 }
    );
  }
}
