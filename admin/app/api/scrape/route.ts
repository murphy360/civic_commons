import { NextRequest, NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

// GET: List all sources with their trigger status
export async function GET() {
  try {
    const sources = await sql<Array<{
      id: number;
      name: string;
      city_id: string;
      source_type: string;
      is_enabled: boolean;
      last_fetched_at: Date | null;
      last_success_at: Date | null;
      trigger_requested_at: Date | null;
    }>>`
      SELECT 
        id, name, city_id, source_type, is_enabled,
        last_fetched_at, last_success_at, trigger_requested_at
      FROM sources
      WHERE is_enabled = true
      ORDER BY name ASC
    `;

    return NextResponse.json({ sources });
  } catch (error) {
    console.error('Failed to fetch sources:', error);
    return NextResponse.json(
      { error: 'Failed to fetch sources' },
      { status: 500 }
    );
  }
}

// POST: Trigger a scrape for one or all sources
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { sourceId, all } = body;

    if (all) {
      // Trigger all enabled sources
      await sql`
        UPDATE sources 
        SET trigger_requested_at = NOW()
        WHERE is_enabled = true
      `;
      return NextResponse.json({ 
        message: 'All sources triggered',
        triggered: 'all'
      });
    } else if (sourceId) {
      // Trigger specific source
      const result = await sql`
        UPDATE sources 
        SET trigger_requested_at = NOW()
        WHERE id = ${sourceId}
        RETURNING name
      `;
      
      if (result.length === 0) {
        return NextResponse.json(
          { error: 'Source not found' },
          { status: 404 }
        );
      }

      return NextResponse.json({ 
        message: `Source "${result[0].name}" triggered`,
        triggered: sourceId
      });
    } else {
      return NextResponse.json(
        { error: 'Must specify sourceId or all=true' },
        { status: 400 }
      );
    }
  } catch (error) {
    console.error('Failed to trigger scrape:', error);
    return NextResponse.json(
      { error: 'Failed to trigger scrape' },
      { status: 500 }
    );
  }
}
