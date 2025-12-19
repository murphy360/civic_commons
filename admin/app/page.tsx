import { sql } from '@/lib/db';
import Link from 'next/link';
import SourceStatusTable from './components/SourceStatusTable';
import NewsletterManager from './components/NewsletterManager';
import AutoRefresh from './components/AutoRefresh';
import { LocalTime } from './components/LocalTime';

export const dynamic = 'force-dynamic';

// Auto-refresh interval in seconds
const AUTO_REFRESH_INTERVAL_SECONDS = parseInt(process.env.ADMIN_AUTO_REFRESH_SECONDS || '30', 10);

// AI Queue Configuration from environment variables
const AI_QUEUE_INTERVAL_SECONDS = parseInt(process.env.AI_QUEUE_INTERVAL_SECONDS || '30', 10);
const AI_QUEUE_BATCH_SIZE = parseInt(process.env.AI_QUEUE_BATCH_SIZE || '1', 10);
const AI_SUMMARY_MAX_AGE_DAYS = parseInt(process.env.AI_SUMMARY_MAX_AGE_DAYS || '0', 10);

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
  trigger_requested_at: Date | null;
}

interface ContentTypeStats {
  total: number;
  ai_summarized: number;
  local: number;
  pending: number;
  aged_out: number;
}

interface RecentAIProcessed {
  id: number;
  type: 'document' | 'event';
  title: string;
  doc_type: string | null;
  meeting_date: Date | null;
  updated_at: Date;
  model_used: string | null;
}

async function getStats() {
  try {
    // Calculate cutoff date for aged-out items
    const cutoffDate = AI_SUMMARY_MAX_AGE_DAYS > 0 
      ? new Date(Date.now() - AI_SUMMARY_MAX_AGE_DAYS * 24 * 60 * 60 * 1000)
      : new Date(0); // Unix epoch if no limit

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
      pending: number;
      aged_out: number;
    }>>`
      SELECT 
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE ai_summary IS NOT NULL)::int as with_summaries,
        COUNT(*) FILTER (WHERE ai_summary IS NULL AND start_time >= ${cutoffDate})::int as pending,
        COUNT(*) FILTER (WHERE ai_summary IS NULL AND start_time < ${cutoffDate})::int as aged_out
      FROM events
    `;

    // Get document statistics by type
    const docTypeStats = await sql<Array<{
      doc_type: string;
      total: number;
      ai_summarized: number;
      local: number;
      pending: number;
      aged_out: number;
    }>>`
      SELECT 
        CASE 
          WHEN document_type = 'agenda' THEN 'agenda'
          WHEN document_type = 'minutes' THEN 'minutes'
          WHEN document_type = 'video' THEN 'video'
          WHEN document_type = 'ordinance' THEN 'ordinance'
          WHEN document_type = 'resolution' THEN 'resolution'
          ELSE 'other'
        END as doc_type,
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE ai_summary IS NOT NULL AND ai_summary != '')::int as ai_summarized,
        COUNT(*) FILTER (WHERE local_path IS NOT NULL)::int as local,
        COUNT(*) FILTER (
          WHERE (ai_summary IS NULL OR ai_summary = '') 
            AND (local_path IS NOT NULL OR (document_type = 'video' AND source_url LIKE '%youtu%'))
            AND COALESCE(meeting_date, created_at) >= ${cutoffDate}
        )::int as pending,
        COUNT(*) FILTER (
          WHERE (ai_summary IS NULL OR ai_summary = '') 
            AND (local_path IS NOT NULL OR (document_type = 'video' AND source_url LIKE '%youtu%'))
            AND COALESCE(meeting_date, created_at) < ${cutoffDate}
        )::int as aged_out
      FROM documents
      GROUP BY 
        CASE 
          WHEN document_type = 'agenda' THEN 'agenda'
          WHEN document_type = 'minutes' THEN 'minutes'
          WHEN document_type = 'video' THEN 'video'
          WHEN document_type = 'ordinance' THEN 'ordinance'
          WHEN document_type = 'resolution' THEN 'resolution'
          ELSE 'other'
        END
    `;

    // Build content type map
    const contentByType: Record<string, ContentTypeStats> = {
      agenda: { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 },
      minutes: { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 },
      video: { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 },
      ordinance: { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 },
      resolution: { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 },
      other: { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 },
    };

    for (const row of docTypeStats) {
      contentByType[row.doc_type] = {
        total: row.total,
        ai_summarized: row.ai_summarized,
        local: row.local,
        pending: row.pending,
        aged_out: row.aged_out,
      };
    }

    // Calculate document totals (excluding videos and legislation for the "Documents" card)
    const docsOnly = ['agenda', 'minutes', 'other'];
    const docsTotals = docsOnly.reduce((acc, type) => ({
      total: acc.total + contentByType[type].total,
      ai_summarized: acc.ai_summarized + contentByType[type].ai_summarized,
      local: acc.local + contentByType[type].local,
      pending: acc.pending + contentByType[type].pending,
      aged_out: acc.aged_out + contentByType[type].aged_out,
    }), { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 });

    // Calculate legislation totals
    const legislationTotals = {
      total: contentByType.ordinance.total + contentByType.resolution.total,
      ai_summarized: contentByType.ordinance.ai_summarized + contentByType.resolution.ai_summarized,
      local: contentByType.ordinance.local + contentByType.resolution.local,
      pending: contentByType.ordinance.pending + contentByType.resolution.pending,
      aged_out: contentByType.ordinance.aged_out + contentByType.resolution.aged_out,
    };

    // Get linking queue count
    const linkingStats = await sql<Array<{ count: number }>>`
      SELECT COUNT(*)::int as count
      FROM documents d 
      WHERE NOT EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id)
        AND d.document_type NOT IN ('ordinance', 'resolution')
        AND (
          (d.ai_summary IS NOT NULL AND d.ai_summary != '')
          OR d.document_type = 'video'
          OR (d.created_at < NOW() - INTERVAL '10 minutes' AND d.local_path IS NULL)
        )
        AND COALESCE(d.meeting_date, d.created_at) >= ${cutoffDate}
    `;

    // Get backfill queue status (if table exists)
    let backfillStatus = { pending: 0, in_progress: 0, completed: 0, failed: 0 };
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

    return {
      sources: {
        total: sourceStats[0]?.total || 0,
        active: sourceStats[0]?.active || 0,
        healthy: sourceStats[0]?.healthy || 0,
        failing: sourceStats[0]?.failing || 0,
      },
      events: {
        total: eventStats[0]?.total || 0,
        ai_summarized: eventStats[0]?.with_summaries || 0,
        pending: eventStats[0]?.pending || 0,
        aged_out: AI_SUMMARY_MAX_AGE_DAYS > 0 ? (eventStats[0]?.aged_out || 0) : 0,
      },
      documents: docsTotals,
      videos: contentByType.video,
      legislation: legislationTotals,
      contentByType,
      linkingPending: linkingStats[0]?.count || 0,
      backfill: backfillStatus,
    };
  } catch (error) {
    console.error('Failed to fetch stats:', error);
    const emptyStats = { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 };
    return {
      sources: { total: 0, active: 0, healthy: 0, failing: 0 },
      events: { total: 0, ai_summarized: 0, pending: 0, aged_out: 0 },
      documents: emptyStats,
      videos: emptyStats,
      legislation: emptyStats,
      contentByType: {
        agenda: emptyStats,
        minutes: emptyStats,
        video: emptyStats,
        ordinance: emptyStats,
        resolution: emptyStats,
        other: emptyStats,
      },
      linkingPending: 0,
      backfill: { pending: 0, in_progress: 0, completed: 0, failed: 0 },
    };
  }
}

async function getSources(): Promise<SourceStatus[]> {
  try {
    return await sql<SourceStatus[]>`
      SELECT 
        id, name, city_id, source_type, is_enabled,
        last_fetched_at, last_success_at, last_error, consecutive_failures,
        trigger_requested_at
      FROM sources
      ORDER BY 
        consecutive_failures DESC,
        last_fetched_at DESC NULLS LAST
    `;
  } catch (error) {
    console.error('Failed to fetch sources:', error);
    return [];
  }
}

async function getRecentAIProcessed(): Promise<RecentAIProcessed[]> {
  try {
    // Get last 5 AI-processed items by ai_summary_updated_at (when AI actually processed them)
    const items = await sql<Array<{
      id: number;
      type: 'document' | 'event';
      title: string;
      doc_type: string | null;
      meeting_date: Date | null;
      updated_at: Date;
      model_used: string | null;
    }>>`
      (
        SELECT 
          id,
          'document'::text as type,
          title,
          document_type as doc_type,
          meeting_date,
          ai_summary_updated_at as updated_at,
          ai_model_used as model_used
        FROM documents
        WHERE ai_summary IS NOT NULL AND ai_summary != ''
          AND ai_summary_updated_at IS NOT NULL
        ORDER BY ai_summary_updated_at DESC
        LIMIT 5
      )
      UNION ALL
      (
        SELECT 
          id,
          'event'::text as type,
          title,
          NULL as doc_type,
          start_time as meeting_date,
          ai_summary_updated_at as updated_at,
          ai_model_used as model_used
        FROM events
        WHERE ai_summary IS NOT NULL
          AND ai_summary_updated_at IS NOT NULL
        ORDER BY ai_summary_updated_at DESC
        LIMIT 5
      )
      ORDER BY updated_at DESC
      LIMIT 5
    `;
    return items;
  } catch (error) {
    console.error('Failed to fetch recent AI processed:', error);
    return [];
  }
}

export default async function AdminDashboard() {
  const stats = await getStats();
  const sources = await getSources();
  const recentAIProcessed = await getRecentAIProcessed();

  // Calculate totals for content breakdown
  const allTypes = ['agenda', 'minutes', 'video', 'ordinance', 'resolution', 'other'] as const;
  const contentTotals = allTypes.reduce((acc, type) => ({
    total: acc.total + stats.contentByType[type].total,
    ai_summarized: acc.ai_summarized + stats.contentByType[type].ai_summarized,
    local: acc.local + stats.contentByType[type].local,
    pending: acc.pending + stats.contentByType[type].pending,
    aged_out: acc.aged_out + stats.contentByType[type].aged_out,
  }), { total: 0, ai_summarized: 0, local: 0, pending: 0, aged_out: 0 });

  // Add events to grand totals
  const grandTotals = {
    total: contentTotals.total + stats.events.total,
    ai_summarized: contentTotals.ai_summarized + stats.events.ai_summarized,
    pending: contentTotals.pending + stats.events.pending,
    aged_out: contentTotals.aged_out + stats.events.aged_out,
  };

  const backfillTotal = stats.backfill.pending + stats.backfill.in_progress + stats.backfill.completed + stats.backfill.failed;

  return (
    <AutoRefresh intervalSeconds={AUTO_REFRESH_INTERVAL_SECONDS}>
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-64 border-r bg-card">
        <div className="flex h-14 items-center border-b px-4">
          <span className="font-bold text-lg">Civic Commons</span>
        </div>
        <nav className="p-4 space-y-2">
          <Link href="/" className="flex items-center gap-3 rounded-lg bg-primary/10 px-3 py-2 text-primary">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
            Dashboard
          </Link>
          <Link href="/sources" className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
            </svg>
            Sources
          </Link>
          <Link href="/cities" className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
            Cities
          </Link>
          <Link href="/logs" className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Logs
          </Link>
          <Link href="/settings" className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Settings
          </Link>
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1">
        {/* Header */}
        <header className="flex h-14 items-center justify-between border-b px-6">
          <h1 className="text-lg font-semibold">Dashboard</h1>
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">
              Last updated: {new Date().toLocaleTimeString()}
            </span>
          </div>
        </header>

        {/* Dashboard Content */}
        <div className="p-6 space-y-6">
          
          {/* Top Stats Cards */}
          <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
            {/* Sources */}
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-medium text-muted-foreground">Sources</p>
              <p className="text-2xl font-bold mt-1">{stats.sources.active}</p>
              <p className={`text-sm ${stats.sources.failing > 0 ? 'text-yellow-600' : 'text-green-600'}`}>
                {stats.sources.healthy} healthy, {stats.sources.failing} failing
              </p>
            </div>

            {/* Events */}
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-medium text-muted-foreground">Events</p>
              <p className="text-2xl font-bold mt-1">{stats.events.total.toLocaleString()}</p>
              <p className="text-sm text-blue-600">{stats.events.ai_summarized} AI ✓</p>
              <p className="text-sm text-muted-foreground">{stats.events.pending} pending</p>
            </div>

            {/* Documents */}
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-medium text-muted-foreground">Documents</p>
              <p className="text-2xl font-bold mt-1">{stats.documents.total.toLocaleString()}</p>
              <p className="text-sm text-purple-600">{stats.documents.ai_summarized} AI ✓</p>
              <p className="text-sm text-muted-foreground">{stats.documents.local} local</p>
            </div>

            {/* Videos */}
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-medium text-muted-foreground">Videos</p>
              <p className="text-2xl font-bold mt-1">{stats.videos.total.toLocaleString()}</p>
              <p className="text-sm text-pink-600">{stats.videos.ai_summarized} AI ✓</p>
              <p className="text-sm text-muted-foreground">{stats.videos.pending} pending</p>
            </div>

            {/* Legislation */}
            <div className="rounded-lg border bg-card p-4">
              <p className="text-sm font-medium text-muted-foreground">Legislation</p>
              <p className="text-2xl font-bold mt-1">{stats.legislation.total.toLocaleString()}</p>
              <p className="text-sm text-indigo-600">{stats.legislation.ai_summarized} AI ✓</p>
              <p className="text-sm text-muted-foreground">{stats.legislation.pending} pending</p>
            </div>
          </div>

          {/* Content Breakdown Table */}
          <div className="rounded-lg border bg-card p-6">
            <div className="flex justify-between items-center mb-4">
              <h2 className="font-semibold">Content Breakdown</h2>
              {AI_SUMMARY_MAX_AGE_DAYS > 0 && (
                <span className="text-xs text-muted-foreground">Last {AI_SUMMARY_MAX_AGE_DAYS} days only</span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 font-medium">Type</th>
                    <th className="text-right py-2 font-medium">Total</th>
                    <th className="text-right py-2 font-medium">AI ✓</th>
                    <th className="text-right py-2 font-medium">Local</th>
                    <th className="text-right py-2 font-medium">Pending</th>
                    <th className="text-right py-2 font-medium text-muted-foreground">Aged Out</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b">
                    <td className="py-2">📅 Events</td>
                    <td className="text-right py-2">{stats.events.total.toLocaleString()}</td>
                    <td className="text-right py-2 text-blue-600">{stats.events.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">—</td>
                    <td className="text-right py-2">{stats.events.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{stats.events.aged_out.toLocaleString()}</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2">📋 Agendas</td>
                    <td className="text-right py-2">{stats.contentByType.agenda.total.toLocaleString()}</td>
                    <td className="text-right py-2 text-purple-600">{stats.contentByType.agenda.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.agenda.local.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.agenda.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{stats.contentByType.agenda.aged_out.toLocaleString()}</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2">📝 Minutes</td>
                    <td className="text-right py-2">{stats.contentByType.minutes.total.toLocaleString()}</td>
                    <td className="text-right py-2 text-purple-600">{stats.contentByType.minutes.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.minutes.local.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.minutes.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{stats.contentByType.minutes.aged_out.toLocaleString()}</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2">🎬 Videos</td>
                    <td className="text-right py-2">{stats.contentByType.video.total.toLocaleString()}</td>
                    <td className="text-right py-2 text-pink-600">{stats.contentByType.video.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">—</td>
                    <td className="text-right py-2">{stats.contentByType.video.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{stats.contentByType.video.aged_out.toLocaleString()}</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2">📜 Ordinances</td>
                    <td className="text-right py-2">{stats.contentByType.ordinance.total.toLocaleString()}</td>
                    <td className="text-right py-2 text-indigo-600">{stats.contentByType.ordinance.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.ordinance.local.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.ordinance.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{stats.contentByType.ordinance.aged_out.toLocaleString()}</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2">📜 Resolutions</td>
                    <td className="text-right py-2">{stats.contentByType.resolution.total.toLocaleString()}</td>
                    <td className="text-right py-2 text-indigo-600">{stats.contentByType.resolution.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.resolution.local.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.resolution.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{stats.contentByType.resolution.aged_out.toLocaleString()}</td>
                  </tr>
                  <tr className="border-b">
                    <td className="py-2">📄 Other</td>
                    <td className="text-right py-2">{stats.contentByType.other.total.toLocaleString()}</td>
                    <td className="text-right py-2 text-gray-600">{stats.contentByType.other.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.other.local.toLocaleString()}</td>
                    <td className="text-right py-2">{stats.contentByType.other.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{stats.contentByType.other.aged_out.toLocaleString()}</td>
                  </tr>
                  <tr className="font-semibold">
                    <td className="py-2">TOTALS</td>
                    <td className="text-right py-2">{grandTotals.total.toLocaleString()}</td>
                    <td className="text-right py-2">{grandTotals.ai_summarized.toLocaleString()}</td>
                    <td className="text-right py-2">{contentTotals.local.toLocaleString()}</td>
                    <td className="text-right py-2">{grandTotals.pending.toLocaleString()}</td>
                    <td className="text-right py-2 text-muted-foreground">{grandTotals.aged_out.toLocaleString()}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Processing Queue */}
          <div className="rounded-lg border bg-card p-6">
            <div className="flex justify-between items-center mb-4">
              <h2 className="font-semibold">Processing Queue</h2>
              <span className="text-xs text-muted-foreground">
                Every {AI_QUEUE_INTERVAL_SECONDS}s ({AI_QUEUE_BATCH_SIZE}/batch)
              </span>
            </div>
            
            {/* Queue Status Boxes */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
              <div className="text-center p-3 rounded-lg bg-cyan-50 dark:bg-cyan-950">
                <p className="text-xl font-bold text-cyan-600">{stats.linkingPending}</p>
                <p className="text-xs text-muted-foreground">🔗 Linking</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-purple-50 dark:bg-purple-950">
                <p className="text-xl font-bold text-purple-600">{stats.documents.pending}</p>
                <p className="text-xs text-muted-foreground">📝 Docs</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-pink-50 dark:bg-pink-950">
                <p className="text-xl font-bold text-pink-600">{stats.videos.pending}</p>
                <p className="text-xs text-muted-foreground">🎬 Videos</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-indigo-50 dark:bg-indigo-950">
                <p className="text-xl font-bold text-indigo-600">{stats.legislation.pending}</p>
                <p className="text-xs text-muted-foreground">📜 Legis.</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-blue-50 dark:bg-blue-950">
                <p className="text-xl font-bold text-blue-600">{stats.events.pending}</p>
                <p className="text-xs text-muted-foreground">📅 Events</p>
              </div>
            </div>

            {/* Progress Bars */}
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Documents</span>
                  <span>{stats.documents.ai_summarized} / {stats.documents.local} ({stats.documents.local > 0 ? Math.round(stats.documents.ai_summarized / stats.documents.local * 100) : 0}%)</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div className="h-full bg-purple-500 rounded-full transition-all" style={{ width: stats.documents.local > 0 ? `${(stats.documents.ai_summarized / stats.documents.local) * 100}%` : '0%' }} />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Videos</span>
                  <span>{stats.videos.ai_summarized} / {stats.videos.total} ({stats.videos.total > 0 ? Math.round(stats.videos.ai_summarized / stats.videos.total * 100) : 0}%)</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div className="h-full bg-pink-500 rounded-full transition-all" style={{ width: stats.videos.total > 0 ? `${(stats.videos.ai_summarized / stats.videos.total) * 100}%` : '0%' }} />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Legislation</span>
                  <span>{stats.legislation.ai_summarized} / {stats.legislation.local} ({stats.legislation.local > 0 ? Math.round(stats.legislation.ai_summarized / stats.legislation.local * 100) : 0}%)</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div className="h-full bg-indigo-500 rounded-full transition-all" style={{ width: stats.legislation.local > 0 ? `${(stats.legislation.ai_summarized / stats.legislation.local) * 100}%` : '0%' }} />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Events</span>
                  <span>{stats.events.ai_summarized} / {stats.events.total} ({stats.events.total > 0 ? Math.round(stats.events.ai_summarized / stats.events.total * 100) : 0}%)</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full transition-all" style={{ width: stats.events.total > 0 ? `${(stats.events.ai_summarized / stats.events.total) * 100}%` : '0%' }} />
                </div>
              </div>
            </div>
          </div>

          {/* Recent AI Processed */}
          <div className="rounded-lg border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold">🤖 Recently AI Processed</h2>
              <Link 
                href="/logs"
                className="text-sm text-primary hover:underline"
              >
                View All Logs →
              </Link>
            </div>
            {recentAIProcessed.length > 0 ? (
              <div className="space-y-2">
                {recentAIProcessed.map((item) => (
                  <div key={`${item.type}-${item.id}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted/50">
                    <span className="text-lg">
                      {item.type === 'event' ? '📅' : 
                        item.doc_type === 'video' ? '🎬' :
                        item.doc_type === 'agenda' ? '📋' :
                        item.doc_type === 'minutes' ? '📝' :
                        item.doc_type === 'ordinance' || item.doc_type === 'resolution' ? '📜' : '📄'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{item.title}</p>
                      <div className="flex gap-2 text-xs text-muted-foreground">
                        <span className="capitalize">{item.type === 'event' ? 'Event' : item.doc_type || 'Document'}</span>
                        {item.meeting_date && (
                          <>
                            <span>•</span>
                            <span>{new Date(item.meeting_date).toLocaleDateString()}</span>
                          </>
                        )}
                        {item.model_used && (
                          <>
                            <span>•</span>
                            <span className="text-blue-600">{item.model_used}</span>
                          </>
                        )}
                      </div>
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                      <LocalTime date={item.updated_at} />
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No items processed yet</p>
            )}
          </div>

          {/* Backfill & Newsletter Row */}
          <div className="grid md:grid-cols-2 gap-6">
            {/* Backfill Queue */}
            <div className="rounded-lg border bg-card p-6">
              <h2 className="font-semibold mb-4">Backfill Queue</h2>
              {backfillTotal > 0 ? (
                <>
                  <div className="grid grid-cols-4 gap-2 mb-4 text-center">
                    <div>
                      <p className="text-lg font-bold text-yellow-600">{stats.backfill.pending}</p>
                      <p className="text-xs text-muted-foreground">⏳ Pending</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-blue-600">{stats.backfill.in_progress}</p>
                      <p className="text-xs text-muted-foreground">🔄 In Progress</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-green-600">{stats.backfill.completed}</p>
                      <p className="text-xs text-muted-foreground">✅ Completed</p>
                    </div>
                    <div>
                      <p className="text-lg font-bold text-red-600">{stats.backfill.failed}</p>
                      <p className="text-xs text-muted-foreground">❌ Failed</p>
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span>Progress</span>
                      <span>{stats.backfill.completed} / {backfillTotal}</span>
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div className="h-full bg-green-500 rounded-full transition-all" style={{ width: `${(stats.backfill.completed / backfillTotal) * 100}%` }} />
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No backfill jobs queued</p>
              )}
            </div>

            {/* Newsletter Management */}
            <NewsletterManager />
          </div>

          {/* Source Status Table */}
          <SourceStatusTable initialSources={sources.map(s => ({
            ...s,
            last_fetched_at: s.last_fetched_at?.toISOString() ?? null,
            last_success_at: s.last_success_at?.toISOString() ?? null,
            trigger_requested_at: s.trigger_requested_at?.toISOString() ?? null,
          }))} />
        </div>
      </main>
    </div>
    </AutoRefresh>
  );
}
