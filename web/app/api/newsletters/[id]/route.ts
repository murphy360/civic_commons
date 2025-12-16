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
  metadata: Record<string, unknown> | null;
  created_at: Date;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const newsletterId = parseInt(id, 10);

    if (isNaN(newsletterId)) {
      return NextResponse.json(
        { error: 'Invalid newsletter ID' },
        { status: 400 }
      );
    }

    const newsletters = await sql<Newsletter[]>`
      SELECT 
        id, city_id, title, period_type, 
        period_start, period_end, status,
        summary_text, pdf_path, pdf_url,
        event_count, document_count, metadata, created_at
      FROM newsletters
      WHERE id = ${newsletterId}
    `;

    if (newsletters.length === 0) {
      return NextResponse.json(
        { error: 'Newsletter not found' },
        { status: 404 }
      );
    }

    return NextResponse.json({ newsletter: newsletters[0] });
  } catch (error) {
    console.error('Failed to fetch newsletter:', error);
    return NextResponse.json(
      { error: 'Failed to fetch newsletter' },
      { status: 500 }
    );
  }
}
