import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * GET /api/queue
 * Returns comprehensive queue status for all processing stages.
 * Used by the admin dashboard for real-time queue monitoring.
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const detailed = searchParams.get('detailed') === 'true';

    // Download queue stats
    const downloadStats = await sql<Array<{
      pending: number;
      in_progress: number;
      completed_today: number;
      failed_today: number;
      oldest_pending: Date | null;
      newest_pending: Date | null;
    }>>`
      SELECT 
        COUNT(*) FILTER (WHERE content_status IN ('discovered', 'download_pending'))::int as pending,
        COUNT(*) FILTER (WHERE content_status = 'downloading')::int as in_progress,
        COUNT(*) FILTER (WHERE content_status NOT IN ('discovered', 'download_pending', 'downloading', 'failed', 'skipped') 
            AND download_completed_at >= CURRENT_DATE)::int as completed_today,
        COUNT(*) FILTER (WHERE content_status = 'failed' 
            AND error_message ILIKE '%download%'
            AND updated_at >= CURRENT_DATE)::int as failed_today,
        MIN(meeting_date) FILTER (WHERE content_status IN ('discovered', 'download_pending')) as oldest_pending,
        MAX(meeting_date) FILTER (WHERE content_status IN ('discovered', 'download_pending')) as newest_pending
      FROM documents
      WHERE source_url IS NOT NULL
    `;

    // Extraction queue stats
    const extractionStats = await sql<Array<{
      pending: number;
      in_progress: number;
      completed_today: number;
      failed_today: number;
    }>>`
      SELECT 
        COUNT(*) FILTER (WHERE content_status IN ('downloaded', 'extraction_pending'))::int as pending,
        COUNT(*) FILTER (WHERE content_status = 'extracting')::int as in_progress,
        COUNT(*) FILTER (WHERE content_status NOT IN ('downloaded', 'extraction_pending', 'extracting', 'failed') 
            AND extraction_completed_at >= CURRENT_DATE)::int as completed_today,
        COUNT(*) FILTER (WHERE content_status = 'failed' 
            AND error_message ILIKE '%extract%'
            AND updated_at >= CURRENT_DATE)::int as failed_today
      FROM documents
      WHERE local_path IS NOT NULL OR content_status IN ('downloaded', 'extraction_pending', 'extracting')
    `;

    // AI queue stats (documents - non-video)
    const aiDocStats = await sql<Array<{
      pending: number;
      in_progress: number;
      completed_today: number;
      failed_today: number;
      failed_total: number;
      retrying: number;
    }>>`
      SELECT 
        COUNT(*) FILTER (WHERE content_status IN ('extracted', 'ai_pending') AND COALESCE(retry_count, 0) < 3)::int as pending,
        COUNT(*) FILTER (WHERE content_status = 'ai_processing')::int as in_progress,
        COUNT(*) FILTER (WHERE content_status = 'completed' 
            AND ai_completed_at >= CURRENT_DATE)::int as completed_today,
        COUNT(*) FILTER (WHERE (content_status = 'failed' OR ai_summary = '[AI_SUMMARY_FAILED]')
            AND updated_at >= CURRENT_DATE)::int as failed_today,
        COUNT(*) FILTER (WHERE content_status = 'failed' OR ai_summary = '[AI_SUMMARY_FAILED]')::int as failed_total,
        COUNT(*) FILTER (WHERE content_status IN ('extracted', 'ai_pending') AND retry_count > 0 AND retry_count < 3)::int as retrying
      FROM documents
      WHERE (document_type != 'video' OR document_type IS NULL)
    `;

    // AI queue stats (videos)
    const aiVideoStats = await sql<Array<{
      pending: number;
      in_progress: number;
      completed_today: number;
      failed_total: number;
      retrying: number;
    }>>`
      SELECT 
        COUNT(*) FILTER (WHERE content_status = 'ai_pending' AND COALESCE(retry_count, 0) < 3)::int as pending,
        COUNT(*) FILTER (WHERE content_status = 'ai_processing')::int as in_progress,
        COUNT(*) FILTER (WHERE content_status = 'completed' 
            AND ai_completed_at >= CURRENT_DATE)::int as completed_today,
        COUNT(*) FILTER (WHERE content_status = 'failed' OR ai_summary = '[AI_SUMMARY_FAILED]')::int as failed_total,
        COUNT(*) FILTER (WHERE content_status = 'ai_pending' AND retry_count > 0 AND retry_count < 3)::int as retrying
      FROM documents
      WHERE document_type = 'video'
    `;

    // AI queue stats (events) - with ready/blocked based on document dependencies
    const aiEventStats = await sql<Array<{
      pending: number;
      ready: number;
      blocked: number;
      completed_today: number;
    }>>`
      WITH event_status AS (
        SELECT 
          e.id,
          (e.ai_summary IS NULL OR e.ai_summary = '') as needs_summary,
          (e.ai_summary IS NOT NULL AND e.ai_summary_updated_at >= CURRENT_DATE) as completed_today,
          NOT EXISTS (
            SELECT 1 FROM event_documents ed
            JOIN documents d ON d.id = ed.document_id
            WHERE ed.event_id = e.id
            AND d.ai_summary IS NULL
          ) as all_docs_ready
        FROM events e
      )
      SELECT 
        COUNT(*) FILTER (WHERE needs_summary)::int as pending,
        COUNT(*) FILTER (WHERE needs_summary AND all_docs_ready)::int as ready,
        COUNT(*) FILTER (WHERE needs_summary AND NOT all_docs_ready)::int as blocked,
        COUNT(*) FILTER (WHERE completed_today)::int as completed_today
      FROM event_status
    `;

    // AI queue stats (summaries) - with ready/blocked based on event dependencies
    const aiSummaryStats = await sql<Array<{
      pending: number;
      ready: number;
      blocked: number;
      in_progress: number;
      completed_today: number;
      failed_today: number;
    }>>`
      WITH summary_status AS (
        SELECT 
          s.id,
          s.status,
          (s.status IN ('pending', 'stale')) as needs_generation,
          (s.status = 'generating') as is_generating,
          (s.status = 'completed' AND s.generation_completed_at >= CURRENT_DATE) as completed_today,
          (s.status = 'failed' AND s.updated_at >= CURRENT_DATE) as failed_today,
          NOT EXISTS (
            SELECT 1 FROM events e
            WHERE e.start_time BETWEEN s.period_start AND s.period_end
            AND (e.ai_summary IS NULL OR e.ai_summary = '')
          ) as all_events_ready
        FROM summaries s
      )
      SELECT 
        COUNT(*) FILTER (WHERE needs_generation)::int as pending,
        COUNT(*) FILTER (WHERE needs_generation AND all_events_ready)::int as ready,
        COUNT(*) FILTER (WHERE needs_generation AND NOT all_events_ready)::int as blocked,
        COUNT(*) FILTER (WHERE is_generating)::int as in_progress,
        COUNT(*) FILTER (WHERE completed_today)::int as completed_today,
        COUNT(*) FILTER (WHERE failed_today)::int as failed_today
      FROM summary_status
    `;

    // Document/Video linking stats
    const linkingStats = await sql<Array<{
      total_docs: number;
      docs_linked: number;
      docs_standalone: number;
      total_videos: number;
      videos_with_date: number;
      videos_linked: number;
      agendas_linked: number;
      agendas_total: number;
      minutes_linked: number;
      minutes_total: number;
      ordinances_total: number;
      resolutions_total: number;
      legislation_mentions: number;
      legislation_linked_events: number;
    }>>`
      SELECT 
        (SELECT COUNT(*) FROM documents WHERE document_type NOT IN ('video', 'ordinance', 'resolution'))::int as total_docs,
        (SELECT COUNT(*) FROM documents d 
         WHERE d.document_type NOT IN ('video', 'ordinance', 'resolution')
         AND EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id))::int as docs_linked,
        (SELECT COUNT(*) FROM documents d 
         WHERE d.document_type NOT IN ('video', 'ordinance', 'resolution')
         AND NOT EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id))::int as docs_standalone,
        (SELECT COUNT(*) FROM documents WHERE document_type = 'video')::int as total_videos,
        (SELECT COUNT(*) FROM documents WHERE document_type = 'video' AND meeting_date IS NOT NULL)::int as videos_with_date,
        (SELECT COUNT(*) FROM documents d 
         WHERE d.document_type = 'video' 
         AND EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id))::int as videos_linked,
        (SELECT COUNT(*) FROM documents d 
         WHERE d.document_type = 'agenda' 
         AND EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id))::int as agendas_linked,
        (SELECT COUNT(*) FROM documents WHERE document_type = 'agenda')::int as agendas_total,
        (SELECT COUNT(*) FROM documents d 
         WHERE d.document_type = 'minutes' 
         AND EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id))::int as minutes_linked,
        (SELECT COUNT(*) FROM documents WHERE document_type = 'minutes')::int as minutes_total,
        (SELECT COUNT(*) FROM documents WHERE document_type = 'ordinance')::int as ordinances_total,
        (SELECT COUNT(*) FROM documents WHERE document_type = 'resolution')::int as resolutions_total,
        (SELECT COUNT(*) FROM legislation_mentions)::int as legislation_mentions,
        (SELECT COUNT(DISTINCT event_id) FROM legislation_mentions WHERE event_id IS NOT NULL)::int as legislation_linked_events
    `;

    const response: Record<string, unknown> = {
      download: downloadStats[0] || { pending: 0, in_progress: 0, completed_today: 0, failed_today: 0 },
      extraction: extractionStats[0] || { pending: 0, in_progress: 0, completed_today: 0, failed_today: 0 },
      ai_documents: aiDocStats[0] || { pending: 0, in_progress: 0, completed_today: 0, failed_today: 0, failed_total: 0, retrying: 0 },
      ai_videos: aiVideoStats[0] || { pending: 0, in_progress: 0, completed_today: 0, failed_total: 0, retrying: 0 },
      ai_events: aiEventStats[0] || { pending: 0, ready: 0, blocked: 0, completed_today: 0 },
      ai_summaries: aiSummaryStats[0] || { pending: 0, ready: 0, blocked: 0, in_progress: 0, completed_today: 0, failed_today: 0 },
      linking: linkingStats[0] || { total_docs: 0, docs_linked: 0, docs_standalone: 0, total_videos: 0, videos_with_date: 0, videos_linked: 0 },
      last_updated: new Date().toISOString(),
    };

    // Calculate totals
    response.total_pending = 
      (downloadStats[0]?.pending || 0) +
      (extractionStats[0]?.pending || 0) +
      (aiDocStats[0]?.pending || 0) +
      (aiVideoStats[0]?.pending || 0) +
      (aiEventStats[0]?.pending || 0) +
      (aiSummaryStats[0]?.pending || 0);

    response.total_in_progress =
      (downloadStats[0]?.in_progress || 0) +
      (extractionStats[0]?.in_progress || 0) +
      (aiDocStats[0]?.in_progress || 0) +
      (aiSummaryStats[0]?.in_progress || 0);

    // Health check
    const failedToday = 
      (downloadStats[0]?.failed_today || 0) +
      (extractionStats[0]?.failed_today || 0) +
      (aiDocStats[0]?.failed_today || 0) +
      (aiSummaryStats[0]?.failed_today || 0);

    response.is_healthy = failedToday < 20;
    response.health_message = failedToday < 20 
      ? 'All systems operational' 
      : `High failure rate: ${failedToday} failures today`;

    // Add detailed items if requested
    if (detailed) {
      // Currently active items
      const activeDownloads = await sql<Array<{
        id: number;
        title: string;
        document_type: string;
        source_url: string;
        meeting_date: Date | null;
      }>>`
        SELECT id, title, document_type, source_url, meeting_date
        FROM documents
        WHERE content_status = 'downloading'
        ORDER BY download_started_at DESC
        LIMIT 5
      `;

      const activeExtractions = await sql<Array<{
        id: number;
        title: string;
        document_type: string;
        local_path: string;
        meeting_date: Date | null;
      }>>`
        SELECT id, title, document_type, local_path, meeting_date
        FROM documents
        WHERE content_status = 'extracting'
        ORDER BY extraction_started_at DESC
        LIMIT 5
      `;

      const activeAI = await sql<Array<{
        id: number;
        title: string;
        document_type: string;
        meeting_date: Date | null;
      }>>`
        SELECT id, title, document_type, meeting_date
        FROM documents
        WHERE content_status = 'ai_processing'
        ORDER BY ai_started_at DESC
        LIMIT 5
      `;

      const recentFailures = await sql<Array<{
        id: number;
        title: string;
        document_type: string;
        content_status: string;
        error_message: string | null;
        retry_count: number;
        updated_at: Date;
      }>>`
        SELECT id, title, document_type, content_status, error_message, retry_count, updated_at
        FROM documents
        WHERE content_status = 'failed'
        ORDER BY updated_at DESC
        LIMIT 10
      `;

      response.active_downloads = activeDownloads;
      response.active_extractions = activeExtractions;
      response.active_ai = activeAI;
      response.recent_failures = recentFailures;
    }

    return NextResponse.json(response);
  } catch (error) {
    console.error('Queue status error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch queue status' },
      { status: 500 }
    );
  }
}
