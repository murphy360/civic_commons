import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * GET /api/activity
 * Returns activity log entries with filtering
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get('limit') || '100');
    const offset = parseInt(searchParams.get('offset') || '0');
    const level = searchParams.get('level'); // info, success, warning, error
    const category = searchParams.get('category'); // download, extraction, ai, scrape, system, event, linking, summary
    const entityType = searchParams.get('entityType'); // document, event, source, summary
    const hours = parseInt(searchParams.get('hours') || '24'); // Time range in hours

    // Build query with filters
    const activities = await sql`
      SELECT 
        id,
        timestamp,
        level,
        category,
        action,
        entity_type,
        entity_id,
        entity_title,
        message,
        details,
        source_name,
        city_id
      FROM activity_log
      WHERE 
        timestamp >= NOW() - make_interval(hours => ${hours})
        ${level ? sql`AND level = ${level}` : sql``}
        ${category ? sql`AND category = ${category}` : sql``}
        ${entityType ? sql`AND entity_type = ${entityType}` : sql``}
      ORDER BY timestamp DESC
      LIMIT ${limit} OFFSET ${offset}
    `;

    // Get counts by category for the time period
    const categoryCounts = await sql`
      SELECT 
        category,
        COUNT(*)::int as count
      FROM activity_log
      WHERE timestamp >= NOW() - make_interval(hours => ${hours})
      GROUP BY category
      ORDER BY count DESC
    `;

    // Get counts by level for the time period
    const levelCounts = await sql`
      SELECT 
        level,
        COUNT(*)::int as count
      FROM activity_log
      WHERE timestamp >= NOW() - make_interval(hours => ${hours})
      GROUP BY level
      ORDER BY 
        CASE level
          WHEN 'error' THEN 1
          WHEN 'warning' THEN 2
          WHEN 'success' THEN 3
          WHEN 'info' THEN 4
        END
    `;

    // Get total count for pagination
    const countResult = await sql`
      SELECT COUNT(*)::int as total
      FROM activity_log
      WHERE 
        timestamp >= NOW() - make_interval(hours => ${hours})
        ${level ? sql`AND level = ${level}` : sql``}
        ${category ? sql`AND category = ${category}` : sql``}
        ${entityType ? sql`AND entity_type = ${entityType}` : sql``}
    `;
    const total = countResult[0]?.total || 0;

    return NextResponse.json({
      activities: activities || [],
      summary: {
        byCategory: categoryCounts || [],
        byLevel: levelCounts || [],
      },
      pagination: {
        limit,
        offset,
        total,
        hasMore: offset + limit < total,
      },
    });
  } catch (error) {
    console.error('Failed to fetch activity logs:', error);
    return NextResponse.json(
      { error: 'Failed to fetch activity logs' },
      { status: 500 }
    );
  }
}
