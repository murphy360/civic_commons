import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * POST /api/summaries/reanalyze
 * Queue a summary period for prioritized (re)analysis.
 * 
 * Body:
 *   - summaryId: number (ID of an existing summary)
 *   OR
 *   - summaryType: 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'annual'
 *   - periodStart: ISO date string
 */
export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { summaryId, summaryType, periodStart } = body;

    // If summaryId provided, update existing summary
    if (summaryId && typeof summaryId === 'number') {
      const existing = await sql`
        SELECT id, summary_type, status FROM summaries WHERE id = ${summaryId}
      `;

      if (!existing || existing.length === 0) {
        return NextResponse.json(
          { error: 'Summary not found' },
          { status: 404 }
        );
      }

      // Reset summary to pending status for regeneration
      await sql`
        UPDATE summaries 
        SET status = 'pending',
            is_stale = true,
            generation_triggered_by = 'manual',
            error_message = NULL
        WHERE id = ${summaryId}
      `;

      return NextResponse.json({
        success: true,
        message: `Summary queued for re-analysis`,
        summaryId,
      });
    }

    // Otherwise, create or queue a new summary by type and period
    if (!summaryType || !['daily', 'weekly', 'monthly', 'quarterly', 'annual'].includes(summaryType)) {
      return NextResponse.json(
        { error: 'Invalid summaryType. Must be one of: daily, weekly, monthly, quarterly, annual' },
        { status: 400 }
      );
    }

    if (!periodStart) {
      return NextResponse.json(
        { error: 'periodStart is required' },
        { status: 400 }
      );
    }

    const startDate = new Date(periodStart);
    let endDate: Date;

    // Calculate period end based on type
    switch (summaryType) {
      case 'daily':
        endDate = new Date(startDate);
        endDate.setHours(23, 59, 59, 999);
        break;
      case 'weekly':
        endDate = new Date(startDate);
        endDate.setDate(endDate.getDate() + 6);
        endDate.setHours(23, 59, 59, 999);
        break;
      case 'monthly':
        endDate = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0, 23, 59, 59, 999);
        break;
      case 'quarterly':
        endDate = new Date(startDate.getFullYear(), startDate.getMonth() + 3, 0, 23, 59, 59, 999);
        break;
      case 'annual':
        endDate = new Date(startDate.getFullYear(), 11, 31, 23, 59, 59, 999);
        break;
      default:
        endDate = new Date(startDate);
    }

    // Check if summary already exists for this period
    const existing = await sql<{ id: number; status: string }[]>`
      SELECT id, status FROM summaries
      WHERE summary_type = ${summaryType} 
        AND period_start = ${startDate}
        AND city_id = 'twinsburg'
    `;

    if (existing && existing.length > 0) {
      // Update existing summary to trigger regeneration
      await sql`
        UPDATE summaries 
        SET status = 'pending',
            is_stale = true,
            generation_triggered_by = 'manual',
            error_message = NULL
        WHERE id = ${existing[0].id}
      `;

      return NextResponse.json({
        success: true,
        message: `${summaryType} summary queued for re-analysis`,
        summaryId: existing[0].id,
        isNew: false,
      });
    }

    // Create new pending summary
    const result = await sql<{ id: number }[]>`
      INSERT INTO summaries (
        city_id, summary_type, period_start, period_end, 
        status, generation_triggered_by
      ) VALUES (
        'twinsburg', 
        ${summaryType}, 
        ${startDate}, 
        ${endDate},
        'pending',
        'manual'
      )
      RETURNING id
    `;

    return NextResponse.json({
      success: true,
      message: `${summaryType} summary created and queued for generation`,
      summaryId: result[0].id,
      isNew: true,
    });
  } catch (error) {
    console.error('Failed to queue summary for reanalysis:', error);
    return NextResponse.json(
      { error: 'Failed to queue summary for re-analysis' },
      { status: 500 }
    );
  }
}
