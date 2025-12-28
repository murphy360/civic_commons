'use client';

import { useState, useEffect } from 'react';
import SourceStatusTable from '../components/SourceStatusTable';
import Sidebar from '../components/Sidebar';
import { adminApi } from '@/lib/adminApi';

// Auto-refresh interval in seconds
const AUTO_REFRESH_INTERVAL_SECONDS = parseInt(process.env.NEXT_PUBLIC_ADMIN_AUTO_REFRESH_SECONDS || '30', 10);

interface SourceStatus {
  id: number;
  name: string;
  city_id: string;
  source_type: string;
  is_enabled: boolean;
  last_fetched_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  trigger_requested_at: string | null;
}

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    const fetchSources = async () => {
      try {
        const data = await adminApi.getSources();
        setSources(data);
      } catch (error) {
        console.error('Failed to fetch sources:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchSources();

    if (!autoRefresh) return;
    const interval = setInterval(fetchSources, AUTO_REFRESH_INTERVAL_SECONDS * 1000);
    return () => clearInterval(interval);
  }, [autoRefresh, AUTO_REFRESH_INTERVAL_SECONDS]);

  const stats = {
    total: sources.length,
    active: sources.filter(s => s.is_enabled).length,
    healthy: sources.filter(s => s.is_enabled && s.consecutive_failures === 0).length,
    failing: sources.filter(s => s.consecutive_failures > 0).length,
  };

  return (
    <div className="flex min-h-screen">
      <Sidebar />

      {/* Main Content */}
      <main className="flex-1">
        {/* Header */}
        <header className="flex h-14 items-center justify-between border-b px-6">
          <h1 className="text-lg font-semibold">Sources</h1>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`px-4 py-2 rounded-lg font-medium transition ${
                autoRefresh 
                  ? 'bg-blue-500 hover:bg-blue-600 text-white' 
                  : 'bg-gray-700 hover:bg-gray-600 text-gray-100'
              }`}
            >
              {autoRefresh ? '⏸ Auto-refresh: ON' : '▶ Auto-refresh: OFF'}
            </button>
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
          {loading ? (
            <div className="flex items-center justify-center p-8">
              <p className="text-muted-foreground">Loading sources...</p>
            </div>
          ) : (
            <SourceStatusTable initialSources={sources} />
          )}
        </div>
      </main>
    </div>
  );
}

