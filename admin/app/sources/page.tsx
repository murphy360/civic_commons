import { sql } from '@/lib/db';
import SourceStatusTable from '../components/SourceStatusTable';
import AutoRefresh from '../components/AutoRefresh';
import Sidebar from '../components/Sidebar';

export const dynamic = 'force-dynamic';

// Auto-refresh interval in seconds
const AUTO_REFRESH_INTERVAL_SECONDS = parseInt(process.env.ADMIN_AUTO_REFRESH_SECONDS || '30', 10);

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

interface SourceStats {
  total: number;
  active: number;
  healthy: number;
  failing: number;
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

async function getSourceStats(): Promise<SourceStats> {
  try {
    const stats = await sql<Array<SourceStats>>`
      SELECT 
        COUNT(*)::int as total,
        COUNT(*) FILTER (WHERE is_enabled = true)::int as active,
        COUNT(*) FILTER (WHERE is_enabled = true AND consecutive_failures = 0)::int as healthy,
        COUNT(*) FILTER (WHERE consecutive_failures > 0)::int as failing
      FROM sources
    `;
    return stats[0] || { total: 0, active: 0, healthy: 0, failing: 0 };
  } catch (error) {
    console.error('Failed to fetch source stats:', error);
    return { total: 0, active: 0, healthy: 0, failing: 0 };
  }
}

export default async function SourcesPage() {
  const sources = await getSources();
  const stats = await getSourceStats();

  return (
    <AutoRefresh intervalSeconds={AUTO_REFRESH_INTERVAL_SECONDS}>
    <div className="flex min-h-screen">
      <Sidebar />

      {/* Main Content */}
      <main className="flex-1">
        {/* Header */}
        <header className="flex h-14 items-center justify-between border-b px-6">
          <h1 className="text-lg font-semibold">Sources</h1>
          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground">
              Last updated: {new Date().toLocaleTimeString()}
            </span>
          </div>
        </header>

        {/* Content */}
        <div className="p-6 space-y-6">
          {/* Stats Cards */}
          <div className="grid grid-cols-4 gap-4">
            <div className="rounded-lg border bg-card p-4">
              <div className="flex items-center gap-2">
                <span className="text-2xl">📊</span>
                <div>
                  <p className="text-2xl font-bold">{stats.total}</p>
                  <p className="text-sm text-muted-foreground">Total Sources</p>
                </div>
              </div>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <div className="flex items-center gap-2">
                <span className="text-2xl">✅</span>
                <div>
                  <p className="text-2xl font-bold text-green-600">{stats.active}</p>
                  <p className="text-sm text-muted-foreground">Active</p>
                </div>
              </div>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <div className="flex items-center gap-2">
                <span className="text-2xl">💚</span>
                <div>
                  <p className="text-2xl font-bold text-green-600">{stats.healthy}</p>
                  <p className="text-sm text-muted-foreground">Healthy</p>
                </div>
              </div>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <div className="flex items-center gap-2">
                <span className="text-2xl">⚠️</span>
                <div>
                  <p className="text-2xl font-bold text-red-600">{stats.failing}</p>
                  <p className="text-sm text-muted-foreground">Failing</p>
                </div>
              </div>
            </div>
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
