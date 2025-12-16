import { sql } from '@/lib/db';
import Link from 'next/link';
import SourceStatusTable from './components/SourceStatusTable';
import NewsletterManager from './components/NewsletterManager';

export const dynamic = 'force-dynamic';

// AI Queue Configuration from environment variables
const AI_QUEUE_INTERVAL_SECONDS = parseInt(process.env.AI_QUEUE_INTERVAL_SECONDS || '30', 10);
const AI_QUEUE_BATCH_SIZE = parseInt(process.env.AI_QUEUE_BATCH_SIZE || '1', 10);

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

async function getStats() {
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
      unlinked: number;
      with_summaries: number;
    }>>`
      SELECT 
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE local_path IS NOT NULL)::int as downloaded,
        COUNT(*) FILTER (WHERE NOT EXISTS (
          SELECT 1 FROM event_documents ed WHERE ed.document_id = documents.id
        ))::int as unlinked,
        COUNT(*) FILTER (WHERE ai_summary IS NOT NULL AND ai_summary != '')::int as with_summaries
      FROM documents
    `;

    // Get AI analysis queue status
    const aiQueueStats = await sql<Array<{
      docs_pending: number;
      docs_linking_pending: number;
      events_pending: number;
    }>>`
      SELECT
        (SELECT COUNT(*)::int FROM documents 
         WHERE (ai_summary IS NULL OR ai_summary = '') 
           AND (local_path IS NOT NULL OR (document_type = 'video' AND source_url LIKE '%youtu%'))
        ) as docs_pending,
        (SELECT COUNT(*)::int FROM documents d 
         WHERE NOT EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id)
           AND (
             (d.ai_summary IS NOT NULL AND d.ai_summary != '')
             OR d.document_type = 'video'
             OR (d.created_at < NOW() - INTERVAL '10 minutes' AND d.local_path IS NULL)
           )
        ) as docs_linking_pending,
        (SELECT COUNT(*)::int FROM events WHERE ai_summary IS NULL) as events_pending
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
        withSummaries: eventStats[0]?.with_summaries || 0,
      },
      documents: {
        total: docStats[0]?.total || 0,
        downloaded: docStats[0]?.downloaded || 0,
        unlinked: docStats[0]?.unlinked || 0,
        withSummaries: docStats[0]?.with_summaries || 0,
      },
      backfill: backfillStatus,
      aiQueue: {
        docsPending: aiQueueStats[0]?.docs_pending || 0,
        docsLinkingPending: aiQueueStats[0]?.docs_linking_pending || 0,
        eventsPending: aiQueueStats[0]?.events_pending || 0,
      },
    };
  } catch (error) {
    console.error('Failed to fetch stats:', error);
    return {
      sources: { total: 0, active: 0, healthy: 0, failing: 0 },
      events: { total: 0, withSummaries: 0 },
      documents: { total: 0, downloaded: 0, unlinked: 0, withSummaries: 0 },
      backfill: { pending: 0, in_progress: 0, completed: 0, failed: 0 },
      aiQueue: { docsPending: 0, docsLinkingPending: 0, eventsPending: 0 },
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

export default async function AdminDashboard() {
  const stats = await getStats();
  const sources = await getSources();

  const statCards = [
    { 
      name: 'Active Sources', 
      value: stats.sources.active.toString(), 
      subtext: `${stats.sources.healthy} healthy, ${stats.sources.failing} failing`,
      color: stats.sources.failing > 0 ? 'text-yellow-600' : 'text-green-600'
    },
    { 
      name: 'Events Indexed', 
      value: stats.events.total.toLocaleString(), 
      subtext: `${stats.events.withSummaries} with AI summaries`,
      color: 'text-blue-600'
    },
    { 
      name: 'Documents', 
      value: stats.documents.total.toLocaleString(), 
      subtext: `${stats.documents.downloaded} downloaded, ${stats.documents.unlinked} unlinked`,
      color: 'text-purple-600'
    },
    { 
      name: 'Backfill Queue', 
      value: stats.backfill.pending.toString(), 
      subtext: `${stats.backfill.completed} done, ${stats.backfill.failed} failed`,
      color: stats.backfill.in_progress > 0 ? 'text-blue-600' : 'text-gray-600'
    },
    {
      name: 'AI Analysis Queue',
      value: (stats.aiQueue.docsPending + stats.aiQueue.docsLinkingPending + stats.aiQueue.eventsPending).toString(),
      subtext: `${stats.aiQueue.docsPending} docs, ${stats.aiQueue.docsLinkingPending} linking, ${stats.aiQueue.eventsPending} events`,
      color: stats.aiQueue.docsPending > 0 ? 'text-orange-600' : 'text-green-600'
    },
  ];

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="w-64 border-r bg-card">
        <div className="flex h-14 items-center border-b px-4">
          <span className="font-bold text-lg">Civic Commons</span>
        </div>
        <nav className="p-4 space-y-2">
          <Link
            href="/"
            className="flex items-center gap-3 rounded-lg bg-primary/10 px-3 py-2 text-primary"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
            Dashboard
          </Link>
          <Link
            href="/sources"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
            </svg>
            Sources
          </Link>
          <Link
            href="/cities"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
            Cities
          </Link>
          <Link
            href="/logs"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Logs
          </Link>
          <Link
            href="/settings"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground"
          >
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
          {/* Stats Grid */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
            {statCards.map((stat) => (
              <div key={stat.name} className="rounded-lg border bg-card p-6">
                <p className="text-sm font-medium text-muted-foreground">{stat.name}</p>
                <div className="mt-2">
                  <p className="text-2xl font-bold">{stat.value}</p>
                  <p className={`text-sm ${stat.color}`}>{stat.subtext}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Source Status Table with Trigger Actions */}
          <SourceStatusTable initialSources={sources.map(s => ({
            ...s,
            last_fetched_at: s.last_fetched_at?.toISOString() ?? null,
            last_success_at: s.last_success_at?.toISOString() ?? null,
            trigger_requested_at: s.trigger_requested_at?.toISOString() ?? null,
          }))} />

          {/* AI Analysis Queue Status */}
          <div className="rounded-lg border bg-card p-6">
            <h2 className="font-semibold mb-4">AI Analysis Queue</h2>
            <div className="grid grid-cols-3 gap-4 mb-6">
              <div className="text-center p-3 rounded-lg bg-orange-50 dark:bg-orange-950">
                <p className="text-2xl font-bold text-orange-600">{stats.aiQueue.docsPending}</p>
                <p className="text-xs text-muted-foreground">Documents Pending Summary</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-blue-50 dark:bg-blue-950">
                <p className="text-2xl font-bold text-blue-600">{stats.aiQueue.docsLinkingPending}</p>
                <p className="text-xs text-muted-foreground">Documents Pending Linking</p>
              </div>
              <div className="text-center p-3 rounded-lg bg-purple-50 dark:bg-purple-950">
                <p className="text-2xl font-bold text-purple-600">{stats.aiQueue.eventsPending}</p>
                <p className="text-xs text-muted-foreground">Events Pending Summary</p>
              </div>
            </div>
            <p className="text-xs text-muted-foreground text-center">
              Queue processes every {AI_QUEUE_INTERVAL_SECONDS} seconds ({AI_QUEUE_BATCH_SIZE} item{AI_QUEUE_BATCH_SIZE !== 1 ? 's' : ''} per batch)
            </p>
          </div>

          {/* AI Summary Progress */}
          <div className="rounded-lg border bg-card p-6">
            <h2 className="font-semibold mb-4">AI Summary Progress</h2>
            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Documents with AI Summaries</span>
                  <span>{stats.documents.withSummaries} / {stats.documents.total}</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-orange-500 rounded-full transition-all"
                    style={{ 
                      width: stats.documents.total > 0 
                        ? `${(stats.documents.withSummaries / stats.documents.total) * 100}%` 
                        : '0%' 
                    }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Events with AI Summaries</span>
                  <span>{stats.events.withSummaries} / {stats.events.total}</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-purple-500 rounded-full transition-all"
                    style={{ 
                      width: stats.events.total > 0 
                        ? `${(stats.events.withSummaries / stats.events.total) * 100}%` 
                        : '0%' 
                    }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Documents Downloaded</span>
                  <span>{stats.documents.downloaded} / {stats.documents.total}</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-blue-500 rounded-full transition-all"
                    style={{ 
                      width: stats.documents.total > 0 
                        ? `${(stats.documents.downloaded / stats.documents.total) * 100}%` 
                        : '0%' 
                    }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span>Backfill Progress</span>
                  <span>
                    {stats.backfill.completed} / {stats.backfill.pending + stats.backfill.in_progress + stats.backfill.completed + stats.backfill.failed}
                  </span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-green-500 rounded-full transition-all"
                    style={{ 
                      width: (() => {
                        const total = stats.backfill.pending + stats.backfill.in_progress + stats.backfill.completed + stats.backfill.failed;
                        return total > 0 ? `${(stats.backfill.completed / total) * 100}%` : '0%';
                      })()
                    }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Newsletter Management */}
          <NewsletterManager />
        </div>
      </main>
    </div>
  );
}
