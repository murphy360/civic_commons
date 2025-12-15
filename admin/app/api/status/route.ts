import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

interface SourceStatus {
  id: number;
  name: string;
  city_id: string;
  source_type: string;
  is_enabled: boolean;
  last_fetched_at: Date | null;
  last_success_at: Date | null;
  last_error: string | null;
  consecutive_failures: number;
}

interface BackfillStatus {
  pending: number;
  in_progress: number;
  completed: number;
  failed: number;
}

interface Stats {
  total_sources: number;
  active_sources: number;
  healthy_sources: number;
  failing_sources: number;
  total_events: number;
  events_with_summaries: number;
  total_documents: number;
  downloaded_documents: number;
}

export async function GET() {
  try {
    // Get source statistics
    const sourceStats = await sql<Array<{
      total: number;
      active: number;
      healthy: number;
      failing: number;
    }>>`
      SELECT 
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE is_enabled = true)::int as active,
        COUNT(*) FILTER (WHERE is_enabled = true AND consecutive_failures = 0)::int as healthy,
        COUNT(*) FILTER (WHERE consecutive_failures > 0)::int as failing
      FROM sources
    `;

    // Get event statistics
    const eventStats = await sql<Array<{
      total: number;
      with_summaries: number;
    }>>`
      SELECT 
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE ai_summary IS NOT NULL)::int as with_summaries
      FROM events
    `;

    // Get document statistics
    const docStats = await sql<Array<{
      total: number;
      downloaded: number;
    }>>`
      SELECT 
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE local_path IS NOT NULL)::int as downloaded
      FROM documents
    `;

    // Get backfill queue status (if table exists)
    let backfillStatus: BackfillStatus = { pending: 0, in_progress: 0, completed: 0, failed: 0 };
    try {
      const backfillStats = await sql<Array<{
        status: string;
        count: number;
      }>>`
        SELECT status, COUNT(*)::int as count
        FROM backfill_queue
        GROUP BY status
      `;
      for (const row of backfillStats) {
        if (row.status === 'pending') backfillStatus.pending = row.count;
        else if (row.status === 'in_progress') backfillStatus.in_progress = row.count;
        else if (row.status === 'completed') backfillStatus.completed = row.count;
        else if (row.status === 'failed') backfillStatus.failed = row.count;
      }
    } catch {
      // Table might not exist yet
    }

    // Get individual source statuses
    const sources = await sql<SourceStatus[]>`
      SELECT 
        id, name, city_id, source_type, is_enabled,
        last_fetched_at, last_success_at, last_error, consecutive_failures
      FROM sources
      ORDER BY 
        consecutive_failures DESC,
        last_fetched_at DESC NULLS LAST
    `;

    // Get recent activity (last 20 scrape events based on source updates)
    const recentActivity = await sql<Array<{
      id: number;
      source_name: string;
      action: string;
      time: Date;
      status: string;
    }>>`
      SELECT 
        s.id,
        s.name as source_name,
        CASE 
          WHEN s.last_error IS NOT NULL AND s.consecutive_failures > 0 
            THEN s.last_error
          WHEN s.last_success_at IS NOT NULL 
            THEN 'Scraped successfully'
          ELSE 'Pending first scrape'
        END as action,
        COALESCE(s.last_fetched_at, s.created_at) as time,
        CASE 
          WHEN s.consecutive_failures > 0 THEN 'error'
          WHEN s.last_success_at IS NOT NULL THEN 'success'
          ELSE 'pending'
        END as status
      FROM sources s
      WHERE s.last_fetched_at IS NOT NULL OR s.created_at > NOW() - INTERVAL '1 day'
      ORDER BY COALESCE(s.last_fetched_at, s.created_at) DESC
      LIMIT 20
    `;

    const stats: Stats = {
      total_sources: sourceStats[0]?.total || 0,
      active_sources: sourceStats[0]?.active || 0,
      healthy_sources: sourceStats[0]?.healthy || 0,
      failing_sources: sourceStats[0]?.failing || 0,
      total_events: eventStats[0]?.total || 0,
      events_with_summaries: eventStats[0]?.with_summaries || 0,
      total_documents: docStats[0]?.total || 0,
      downloaded_documents: docStats[0]?.downloaded || 0,
    };

    return NextResponse.json({
      stats,
      backfill: backfillStatus,
      sources,
      recentActivity,
    });
  } catch (error) {
    console.error('Failed to fetch status:', error);
    return NextResponse.json(
      { error: 'Failed to fetch status' },
      { status: 500 }
    );
  }
}
