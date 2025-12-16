import { NextRequest, NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

interface Newsletter {
  id: number;
  city_id: string;
  title: string;
  period_type: string;
  period_start: Date;
  period_end: Date;
  status: string;
  summary_text: string | null;
  pdf_path: string | null;
  pdf_url: string | null;
  event_count: number;
  document_count: number;
  created_at: Date;
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const periodType = searchParams.get('period_type');
    const limit = parseInt(searchParams.get('limit') || '20', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);

    let newsletters: Newsletter[];
    let total: number;

    if (periodType) {
      // Filter by period type
      const countResult = await sql<{ count: number }[]>`
        SELECT COUNT(*)::int as count 
        FROM newsletters 
        WHERE status = 'completed' AND period_type = ${periodType}
      `;
      total = countResult[0]?.count || 0;

      newsletters = await sql<Newsletter[]>`
        SELECT 
          id, city_id, title, period_type, 
          period_start, period_end, status,
          summary_text, pdf_path, pdf_url,
          event_count, document_count, created_at
        FROM newsletters
        WHERE status = 'completed' AND period_type = ${periodType}
        ORDER BY period_start DESC
        LIMIT ${limit} OFFSET ${offset}
      `;
    } else {
      // Get all completed newsletters
      const countResult = await sql<{ count: number }[]>`
        SELECT COUNT(*)::int as count 
        FROM newsletters 
        WHERE status = 'completed'
      `;
      total = countResult[0]?.count || 0;

      newsletters = await sql<Newsletter[]>`
        SELECT 
          id, city_id, title, period_type, 
          period_start, period_end, status,
          summary_text, pdf_path, pdf_url,
          event_count, document_count, created_at
        FROM newsletters
        WHERE status = 'completed'
        ORDER BY period_start DESC
        LIMIT ${limit} OFFSET ${offset}
      `;
    }

    return NextResponse.json({ 
      newsletters,
      total,
      offset,
      limit,
      hasMore: offset + newsletters.length < total
    });
  } catch (error) {
    console.error('Failed to fetch newsletters:', error);
    return NextResponse.json(
      { error: 'Failed to fetch newsletters' },
      { status: 500 }
    );
  }
}
