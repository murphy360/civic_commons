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
  event_count: number;
  document_count: number;
  error_message: string | null;
  created_at: Date;
  generation_started_at: Date | null;
  generation_completed_at: Date | null;
}

// GET: List all newsletters with status
export async function GET() {
  try {
    const newsletters = await sql<Newsletter[]>`
      SELECT 
        id, city_id, title, period_type,
        period_start, period_end, status,
        event_count, document_count, error_message,
        created_at, generation_started_at, generation_completed_at
      FROM newsletters
      ORDER BY period_start DESC
      LIMIT 50
    `;

    // Get stats
    const stats = await sql<Array<{
      total: number;
      completed: number;
      pending: number;
      failed: number;
    }>>`
      SELECT
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE status = 'completed')::int as completed,
        COUNT(*) FILTER (WHERE status IN ('pending', 'generating'))::int as pending,
        COUNT(*) FILTER (WHERE status = 'failed')::int as failed
      FROM newsletters
    `;

    return NextResponse.json({ 
      newsletters,
      stats: stats[0] || { total: 0, completed: 0, pending: 0, failed: 0 }
    });
  } catch (error) {
    console.error('Failed to fetch newsletters:', error);
    return NextResponse.json(
      { error: 'Failed to fetch newsletters' },
      { status: 500 }
    );
  }
}

// POST: Trigger newsletter generation
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { period_type } = body;

    if (!period_type || !['daily', 'weekly', 'monthly', 'quarterly', 'annual'].includes(period_type)) {
      return NextResponse.json(
        { error: 'Invalid period_type. Must be one of: daily, weekly, monthly, quarterly, annual' },
        { status: 400 }
      );
    }

    // Calculate period dates based on type
    const now = new Date();
    let periodStart: Date;
    let periodEnd: Date;

    switch (period_type) {
      case 'daily':
        periodStart = new Date(now);
        periodStart.setDate(periodStart.getDate() - 1);
        periodStart.setHours(0, 0, 0, 0);
        periodEnd = new Date(periodStart);
        periodEnd.setHours(23, 59, 59, 999);
        break;
      case 'weekly':
        const daysSinceMonday = now.getDay() === 0 ? 6 : now.getDay() - 1;
        periodStart = new Date(now);
        periodStart.setDate(periodStart.getDate() - daysSinceMonday - 7);
        periodStart.setHours(0, 0, 0, 0);
        periodEnd = new Date(periodStart);
        periodEnd.setDate(periodEnd.getDate() + 6);
        periodEnd.setHours(23, 59, 59, 999);
        break;
      case 'monthly':
        periodStart = new Date(now.getFullYear(), now.getMonth() - 1, 1);
        periodEnd = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59, 999);
        break;
      case 'quarterly':
        const currentQuarter = Math.floor(now.getMonth() / 3);
        const lastQuarter = currentQuarter === 0 ? 3 : currentQuarter - 1;
        const lastQuarterYear = currentQuarter === 0 ? now.getFullYear() - 1 : now.getFullYear();
        periodStart = new Date(lastQuarterYear, lastQuarter * 3, 1);
        periodEnd = new Date(lastQuarterYear, lastQuarter * 3 + 3, 0, 23, 59, 59, 999);
        break;
      case 'annual':
        periodStart = new Date(now.getFullYear() - 1, 0, 1);
        periodEnd = new Date(now.getFullYear() - 1, 11, 31, 23, 59, 59, 999);
        break;
      default:
        periodStart = new Date(now);
        periodEnd = new Date(now);
    }

    // Check if newsletter already exists
    const existing = await sql<{ id: number }[]>`
      SELECT id FROM newsletters
      WHERE period_type = ${period_type} AND period_start = ${periodStart}
    `;

    if (existing.length > 0) {
      return NextResponse.json(
        { error: 'Newsletter for this period already exists', id: existing[0].id },
        { status: 409 }
      );
    }

    // Create pending newsletter record (worker will pick it up)
    const result = await sql<{ id: number }[]>`
      INSERT INTO newsletters (
        city_id, title, period_type, period_start, period_end, status
      ) VALUES (
        'twinsburg',
        ${`${period_type.charAt(0).toUpperCase() + period_type.slice(1)} Newsletter - ${periodStart.toLocaleDateString()}`},
        ${period_type},
        ${periodStart},
        ${periodEnd},
        'pending'
      )
      RETURNING id
    `;

    return NextResponse.json({ 
      message: `${period_type} newsletter queued for generation`,
      id: result[0].id,
      period_start: periodStart,
      period_end: periodEnd
    });
  } catch (error) {
    console.error('Failed to trigger newsletter generation:', error);
    return NextResponse.json(
      { error: 'Failed to trigger newsletter generation' },
      { status: 500 }
    );
  }
}
