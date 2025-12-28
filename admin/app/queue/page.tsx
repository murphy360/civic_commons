'use client';

import { useState, useEffect, useCallback } from 'react';
import Sidebar from '../components/Sidebar';
import { adminApi } from '@/lib/adminApi';
import Link from 'next/link';

interface QueueItem {
  id: number;
  title: string;
  document_type: string | null;
  content_status: string;
  source_url: string | null;
  local_path: string | null;
  meeting_date: string | null;
  error_message: string | null;
  retry_count: number;
  file_size_bytes: number | null;
  discovered_at: string | null;
  download_started_at: string | null;
  download_completed_at: string | null;
  extraction_started_at: string | null;
  extraction_completed_at: string | null;
  ai_started_at: string | null;
  ai_completed_at: string | null;
  created_at: string;
  updated_at: string;
  source_name: string | null;
  city_id: string | null;
}

type StatusFilter = 'pending' | 'in_progress' | 'failed' | 'all';

const STATUS_ORDER: Record<string, number> = {
  'discovered': 1,
  'download_pending': 2,
  'downloading': 3,
  'downloaded': 4,
  'extraction_pending': 5,
  'extracting': 6,
  'extracted': 7,
  'ai_pending': 8,
  'ai_processing': 9,
  'completed': 10,
  'failed': 11,
  'skipped': 12,
};

const STATUS_INFO: Record<string, { label: string; color: string; bgColor: string; icon: string }> = {
  'discovered': { label: 'Discovered', color: 'text-blue-700', bgColor: 'bg-blue-100', icon: '📌' },
  'download_pending': { label: 'Download Pending', color: 'text-yellow-700', bgColor: 'bg-yellow-100', icon: '⏳' },
  'downloading': { label: 'Downloading', color: 'text-cyan-700', bgColor: 'bg-cyan-100', icon: '⬇️' },
  'downloaded': { label: 'Downloaded', color: 'text-green-700', bgColor: 'bg-green-100', icon: '✓' },
  'extraction_pending': { label: 'Extraction Pending', color: 'text-yellow-700', bgColor: 'bg-yellow-100', icon: '⏳' },
  'extracting': { label: 'Extracting', color: 'text-purple-700', bgColor: 'bg-purple-100', icon: '🔨' },
  'extracted': { label: 'Extracted', color: 'text-indigo-700', bgColor: 'bg-indigo-100', icon: '✓' },
  'ai_pending': { label: 'AI Pending', color: 'text-orange-700', bgColor: 'bg-orange-100', icon: '⏳' },
  'ai_processing': { label: 'AI Processing', color: 'text-pink-700', bgColor: 'bg-pink-100', icon: '🤖' },
  'completed': { label: 'Completed', color: 'text-emerald-700', bgColor: 'bg-emerald-100', icon: '✓' },
  'failed': { label: 'Failed', color: 'text-red-700', bgColor: 'bg-red-100', icon: '❌' },
  'skipped': { label: 'Skipped', color: 'text-gray-700', bgColor: 'bg-gray-100', icon: '⊘' },
};

function getDocTypeIcon(docType: string | null): string {
  switch (docType) {
    case 'video': return '🎬';
    case 'agenda': return '📋';
    case 'minutes': return '📝';
    case 'ordinance': return '📜';
    case 'resolution': return '📜';
    default: return '📄';
  }
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString('en-US', { 
    month: 'short', 
    day: 'numeric',
    year: 'numeric'
  });
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 0) return 'Future';
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchItems = useCallback(async () => {
    try {
      setLoading(true);
      // Fetch items - don't filter by stage to get all stages
      const data = await adminApi.getQueueItems({
        limit: 200,
        offset: 0
      });
      
      let filtered = data.items || [];
      
      // Filter based on selection
      if (statusFilter === 'pending') {
        filtered = filtered.filter((item: QueueItem) =>
          ['discovered', 'download_pending', 'downloading', 'downloaded', 'extraction_pending', 'extracting', 'extracted', 'ai_pending'].includes(item.content_status)
        );
      } else if (statusFilter === 'in_progress') {
        filtered = filtered.filter((item: QueueItem) =>
          ['downloading', 'extracting', 'ai_processing'].includes(item.content_status)
        );
      } else if (statusFilter === 'failed') {
        filtered = filtered.filter((item: QueueItem) => item.content_status === 'failed');
      }
      
      // Sort by status order (forward-looking)
      filtered.sort((a: QueueItem, b: QueueItem) => {
        const orderA = STATUS_ORDER[a.content_status] || 999;
        const orderB = STATUS_ORDER[b.content_status] || 999;
        return orderA - orderB;
      });
      
      setItems(filtered);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  // Initial load
  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchItems, 10000); // 10 seconds
    return () => clearInterval(interval);
  }, [autoRefresh, fetchItems]);

  if (loading) {
    return (
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="max-w-7xl mx-auto">
            <div className="animate-pulse space-y-4">
              <div className="h-8 bg-gray-200 rounded w-1/4"></div>
              <div className="space-y-3">
                {[1, 2, 3].map(i => (
                  <div key={i} className="h-20 bg-gray-200 rounded"></div>
                ))}
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  const counts = {
    pending: items.filter(i => ['discovered', 'download_pending', 'downloading', 'downloaded', 'extraction_pending', 'extracting', 'extracted', 'ai_pending'].includes(i.content_status)).length,
    in_progress: items.filter(i => ['downloading', 'extracting', 'ai_processing'].includes(i.content_status)).length,
    failed: items.filter(i => i.content_status === 'failed').length,
  };

  return (
    <div className="flex min-h-screen">
      <Sidebar />

      {/* Main Content */}
      <main className="flex-1">
        {/* Header */}
        <header className="flex h-14 items-center justify-between border-b px-6">
          <h1 className="text-lg font-semibold">Processing Queue</h1>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded"
              />
              Auto-refresh
            </label>
            <Link 
              href="/pipeline" 
              className="text-sm text-blue-600 hover:text-blue-700 underline"
            >
              View Pipeline
            </Link>
          </div>
        </header>

        <div className="p-6 space-y-6">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
              {error}
            </div>
          )}

          {/* Filter Tabs */}
          <div className="flex gap-2 border-b">
            {(['pending', 'in_progress', 'failed'] as const).map((filter) => (
              <button
                key={filter}
                onClick={() => setStatusFilter(filter)}
                className={`px-4 py-2 font-medium text-sm border-b-2 transition ${
                  statusFilter === filter
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {filter === 'pending' && `⏳ Pending (${counts.pending})`}
                {filter === 'in_progress' && `⚙️ In Progress (${counts.in_progress})`}
                {filter === 'failed' && `❌ Failed (${counts.failed})`}
              </button>
            ))}
          </div>

          {/* Queue Items */}
          {items.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-4xl mb-2">
                {statusFilter === 'pending' && '✨'}
                {statusFilter === 'in_progress' && '✓'}
                {statusFilter === 'failed' && '✅'}
              </div>
              <p className="text-muted-foreground text-lg">
                {statusFilter === 'pending' && 'No items pending!'}
                {statusFilter === 'in_progress' && 'Nothing currently processing'}
                {statusFilter === 'failed' && 'No failed items'}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {items.map((item) => {
                const status = STATUS_INFO[item.content_status] || STATUS_INFO['skipped'];
                const isNext = items.indexOf(item) < 3; // Highlight the next 3
                
                return (
                  <div
                    key={item.id}
                    className={`border rounded-lg p-4 transition ${
                      isNext && statusFilter === 'pending'
                        ? 'bg-blue-50 border-blue-300 ring-2 ring-blue-200'
                        : 'bg-card hover:bg-muted/30'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-2xl">{getDocTypeIcon(item.document_type)}</span>
                          <div className="min-w-0">
                            <h3 className="font-semibold truncate max-w-[600px]">{item.title}</h3>
                            <div className="text-xs text-muted-foreground">
                              {item.document_type} • {item.source_name || 'Unknown source'} • ID: {item.id}
                            </div>
                          </div>
                        </div>

                        {/* Status Badge */}
                        <div className="flex items-center gap-2 mt-2">
                          <span className={`inline-block px-2 py-1 rounded text-xs font-medium ${status.bgColor} ${status.color}`}>
                            {status.icon} {status.label}
                          </span>
                          {item.retry_count > 0 && (
                            <span className="text-xs text-orange-600 bg-orange-50 px-2 py-1 rounded">
                              Retried {item.retry_count} time{item.retry_count > 1 ? 's' : ''}
                            </span>
                          )}
                        </div>

                        {/* Error Message if present */}
                        {item.error_message && (
                          <div className="mt-2 text-xs text-red-600 bg-red-50 p-2 rounded max-w-[600px]">
                            <strong>Error:</strong> {item.error_message}
                          </div>
                        )}

                        {/* Meeting Date */}
                        {item.meeting_date && (
                          <div className="mt-2 text-xs text-muted-foreground">
                            📅 Meeting Date: <span className="font-medium">{formatDate(item.meeting_date)}</span>
                          </div>
                        )}
                      </div>

                      {/* Right column: details */}
                      <div className="text-right text-sm space-y-2">
                        <div className="text-xs text-muted-foreground">
                          Size: <span className="font-medium">{formatFileSize(item.file_size_bytes)}</span>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Updated: <span className="font-medium">{formatRelativeTime(item.updated_at)}</span>
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Discovered: <span className="font-medium">{formatRelativeTime(item.discovered_at)}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Summary */}
          <div className="border-t pt-6 text-sm text-muted-foreground">
            <p>
              Showing <strong>{items.length}</strong> items • 
              <strong className="ml-2">{counts.pending}</strong> pending • 
              <strong className="ml-2">{counts.in_progress}</strong> in progress • 
              <strong className="ml-2">{counts.failed}</strong> failed
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
