import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

// Calculate cutoff date based on AI_SUMMARY_MAX_AGE_DAYS (0 = no limit)
const AI_SUMMARY_MAX_AGE_DAYS = parseInt(process.env.AI_SUMMARY_MAX_AGE_DAYS || '365');
// Use a very large number if 0 (no limit) - effectively 100 years
const EFFECTIVE_MAX_AGE = AI_SUMMARY_MAX_AGE_DAYS > 0 ? AI_SUMMARY_MAX_AGE_DAYS : 36500;

export async function GET() {
  try {
    const cutoffDate = AI_SUMMARY_MAX_AGE_DAYS > 0 
      ? new Date(Date.now() - AI_SUMMARY_MAX_AGE_DAYS * 24 * 60 * 60 * 1000)
      : new Date(0);

    // Get completed AI processing (most recent 100)
    const completed = await sql<Array<{
      id: number;
      type: 'document' | 'event' | 'summary';
      title: string;
      doc_type: string | null;
      summary_type: string | null;
      meeting_date: Date | null;
      period_start: Date | null;
      period_end: Date | null;
      processed_at: Date;
      model_used: string | null;
      status: string;
      source_name: string | null;
    }>>`
      (
        SELECT 
          d.id,
          'document'::text as type,
          d.title,
          d.document_type as doc_type,
          NULL as summary_type,
          d.meeting_date,
          NULL::timestamp as period_start,
          NULL::timestamp as period_end,
          d.ai_summary_updated_at as processed_at,
          d.ai_model_used as model_used,
          'completed' as status,
          s.name as source_name
        FROM documents d
        LEFT JOIN sources s ON d.source_id = s.id
        WHERE d.ai_summary IS NOT NULL AND d.ai_summary != ''
          AND d.ai_summary NOT LIKE '[AI_SUMMARY_FAILED]%'
          AND d.ai_summary_updated_at IS NOT NULL
      )
      UNION ALL
      (
        SELECT 
          e.id,
          'event'::text as type,
          e.title,
          NULL as doc_type,
          NULL as summary_type,
          e.start_time as meeting_date,
          NULL::timestamp as period_start,
          NULL::timestamp as period_end,
          e.ai_summary_updated_at as processed_at,
          e.ai_model_used as model_used,
          'completed' as status,
          NULL as source_name
        FROM events e
        WHERE e.ai_summary IS NOT NULL AND e.ai_summary != ''
          AND e.ai_summary NOT LIKE '[AI_SUMMARY_FAILED]%'
          AND e.ai_summary_updated_at IS NOT NULL
      )
      UNION ALL
      (
        SELECT 
          sm.id,
          'summary'::text as type,
          COALESCE(sm.title, sm.summary_type || ' Summary') as title,
          NULL as doc_type,
          sm.summary_type,
          NULL::timestamp as meeting_date,
          sm.period_start,
          sm.period_end,
          sm.updated_at as processed_at,
          sm.model_used,
          sm.status,
          NULL as source_name
        FROM summaries sm
        WHERE sm.status = 'completed'
      )
      ORDER BY processed_at DESC
      LIMIT 100
    `;

    // Get pending/scheduled items (exclude failed, wrapped in subquery to allow complex ORDER BY)
    const pending = await sql<Array<{
      id: number;
      type: 'document' | 'event' | 'summary';
      title: string;
      doc_type: string | null;
      summary_type: string | null;
      meeting_date: Date | null;
      period_start: Date | null;
      period_end: Date | null;
      created_at: Date;
      status: string;
      priority: number | null;
      source_name: string | null;
    }>>`
      SELECT * FROM (
        (
          -- Documents waiting for AI processing (exclude failed)
          SELECT 
            d.id,
            'document'::text as type,
            d.title,
            d.document_type as doc_type,
            NULL as summary_type,
            COALESCE(d.meeting_date, d.created_at) as item_date,
            d.meeting_date,
            NULL::timestamp as period_start,
            NULL::timestamp as period_end,
            d.created_at,
            'pending' as status,
            NULL::int as priority,
            s.name as source_name
          FROM documents d
          LEFT JOIN sources s ON d.source_id = s.id
          WHERE (d.ai_summary IS NULL OR d.ai_summary = '')
            AND (d.ai_summary IS NULL OR d.ai_summary NOT LIKE '[AI_SUMMARY_FAILED]%')
            AND (d.local_path IS NOT NULL OR (d.document_type = 'video' AND d.source_url LIKE '%youtu%'))
            AND COALESCE(d.meeting_date, d.created_at) >= NOW() - INTERVAL '1 day' * ${EFFECTIVE_MAX_AGE}
        )
        UNION ALL
        (
          -- Events waiting for AI processing (exclude failed)
          SELECT 
            e.id,
            'event'::text as type,
            e.title,
            NULL as doc_type,
            NULL as summary_type,
            COALESCE(e.start_time, e.created_at) as item_date,
            e.start_time as meeting_date,
            NULL::timestamp as period_start,
            NULL::timestamp as period_end,
            e.created_at,
            'pending' as status,
            NULL::int as priority,
            NULL as source_name
          FROM events e
          WHERE (e.ai_summary IS NULL OR e.ai_summary = '')
            AND (e.ai_summary IS NULL OR e.ai_summary NOT LIKE '[AI_SUMMARY_FAILED]%')
            AND COALESCE(e.start_time, e.created_at) >= NOW() - INTERVAL '1 day' * ${EFFECTIVE_MAX_AGE}
        )
        UNION ALL
        (
          -- Summaries pending or generating (weekly, monthly, quarterly, annual)
          SELECT 
            sm.id,
            'summary'::text as type,
            COALESCE(sm.title, sm.summary_type || ' Summary') as title,
            NULL as doc_type,
            sm.summary_type,
            sm.period_end as item_date,
            NULL::timestamp as meeting_date,
            sm.period_start,
            sm.period_end,
            sm.created_at,
            sm.status,
            NULL::int as priority,
            NULL as source_name
          FROM summaries sm
          WHERE sm.status IN ('pending', 'generating', 'stale')
            AND sm.period_end >= NOW() - INTERVAL '1 day' * ${EFFECTIVE_MAX_AGE}
        )
      ) AS combined
      ORDER BY item_date DESC NULLS LAST
      LIMIT 200
    `;

    // Get failed items
    const failed = await sql<Array<{
      id: number;
      type: 'document' | 'event' | 'summary';
      title: string;
      doc_type: string | null;
      summary_type: string | null;
      meeting_date: Date | null;
      period_start: Date | null;
      period_end: Date | null;
      failed_at: Date;
      error_message: string | null;
      source_name: string | null;
    }>>`
      (
        -- Failed documents
        SELECT 
          d.id,
          'document'::text as type,
          d.title,
          d.document_type as doc_type,
          NULL as summary_type,
          d.meeting_date,
          NULL::timestamp as period_start,
          NULL::timestamp as period_end,
          d.ai_summary_updated_at as failed_at,
          SUBSTRING(d.ai_summary FROM 20 FOR 500) as error_message,
          s.name as source_name
        FROM documents d
        LEFT JOIN sources s ON d.source_id = s.id
        WHERE d.ai_summary LIKE '[AI_SUMMARY_FAILED]%'
      )
      UNION ALL
      (
        -- Failed events
        SELECT 
          e.id,
          'event'::text as type,
          e.title,
          NULL as doc_type,
          NULL as summary_type,
          e.start_time as meeting_date,
          NULL::timestamp as period_start,
          NULL::timestamp as period_end,
          e.ai_summary_updated_at as failed_at,
          SUBSTRING(e.ai_summary FROM 20 FOR 500) as error_message,
          NULL as source_name
        FROM events e
        WHERE e.ai_summary LIKE '[AI_SUMMARY_FAILED]%'
      )
      UNION ALL
      (
        -- Failed summaries
        SELECT 
          sm.id,
          'summary'::text as type,
          COALESCE(sm.title, sm.summary_type || ' Summary') as title,
          NULL as doc_type,
          sm.summary_type,
          NULL::timestamp as meeting_date,
          sm.period_start,
          sm.period_end,
          sm.updated_at as failed_at,
          sm.error_message,
          NULL as source_name
        FROM summaries sm
        WHERE sm.status = 'failed'
      )
      ORDER BY failed_at DESC NULLS LAST
      LIMIT 100
    `;

    return NextResponse.json({
      completed: completed.map(item => ({
        ...item,
        meeting_date: item.meeting_date?.toISOString() || null,
        period_start: item.period_start?.toISOString() || null,
        period_end: item.period_end?.toISOString() || null,
        processed_at: item.processed_at?.toISOString() || null,
      })),
      pending: pending.map(item => ({
        ...item,
        meeting_date: item.meeting_date?.toISOString() || null,
        period_start: item.period_start?.toISOString() || null,
        period_end: item.period_end?.toISOString() || null,
        created_at: item.created_at?.toISOString() || null,
      })),
      failed: failed.map(item => ({
        ...item,
        meeting_date: item.meeting_date?.toISOString() || null,
        period_start: item.period_start?.toISOString() || null,
        period_end: item.period_end?.toISOString() || null,
        failed_at: item.failed_at?.toISOString() || null,
      })),
    });
  } catch (error) {
    console.error('Failed to fetch AI logs:', error);
    return NextResponse.json(
      { error: 'Failed to fetch AI logs', completed: [], pending: [], failed: [] },
      { status: 500 }
    );
  }
}
