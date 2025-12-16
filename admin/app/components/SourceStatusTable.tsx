'use client';

import { useState, useCallback } from 'react';

interface Source {
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

function formatTimeAgo(dateStr: string | null): string {
  if (!dateStr) return 'Never';
  const now = new Date();
  const then = new Date(dateStr);
  const diffMs = now.getTime() - then.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

function getStatusColor(source: Source): string {
  if (!source.is_enabled) return 'bg-gray-400';
  if (source.consecutive_failures > 0) return 'bg-red-500';
  if (source.last_success_at) return 'bg-green-500';
  return 'bg-yellow-500';
}

function getStatusText(source: Source): string {
  if (!source.is_enabled) return 'Disabled';
  if (source.consecutive_failures > 0) return `Failed (${source.consecutive_failures}x)`;
  if (source.last_success_at) return 'Healthy';
  return 'Pending';
}

function isPending(source: Source): boolean {
  if (!source.trigger_requested_at) return false;
  if (!source.last_fetched_at) return true;
  return new Date(source.trigger_requested_at) > new Date(source.last_fetched_at);
}

interface SourceStatusTableProps {
  initialSources: Source[];
}

export default function SourceStatusTable({ initialSources }: SourceStatusTableProps) {
  const [sources, setSources] = useState<Source[]>(initialSources);
  const [triggering, setTriggering] = useState<number | 'all' | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const refreshSources = useCallback(async () => {
    try {
      const response = await fetch('/api/scrape');
      if (!response.ok) throw new Error('Failed to fetch sources');
      const data = await response.json();
      setSources(data.sources || []);
    } catch (error) {
      console.error('Failed to refresh sources:', error);
    }
  }, []);

  const triggerScrape = async (sourceId?: number) => {
    const key = sourceId || 'all';
    setTriggering(key);
    setMessage(null);

    try {
      const response = await fetch('/api/scrape', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sourceId ? { sourceId } : { all: true }),
      });

      if (!response.ok) throw new Error('Failed to trigger scrape');
      
      const data = await response.json();
      setMessage({ type: 'success', text: data.message });
      
      // Refresh sources after a short delay
      setTimeout(refreshSources, 1000);
    } catch (error) {
      console.error('Failed to trigger scrape:', error);
      setMessage({ type: 'error', text: 'Failed to trigger scrape' });
    } finally {
      setTriggering(null);
    }
  };

  // Auto-clear message after 5 seconds
  if (message) {
    setTimeout(() => setMessage(null), 5000);
  }

  return (
    <div className="rounded-lg border bg-card">
      <div className="flex items-center justify-between border-b p-4">
        <div className="flex items-center gap-4">
          <h2 className="font-semibold">Source Status</h2>
          {message && (
            <span className={`text-sm px-3 py-1 rounded-full ${
              message.type === 'success' 
                ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' 
                : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
            }`}>
              {message.text}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {sources.length} source{sources.length !== 1 ? 's' : ''}
          </span>
          <button
            onClick={() => triggerScrape()}
            disabled={triggering !== null}
            className="px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium flex items-center gap-2"
          >
            {triggering === 'all' ? (
              <>
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Triggering...
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Run All
              </>
            )}
          </button>
        </div>
      </div>
      
      {sources.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground">
          No sources configured yet. The worker will create sources on first scrape.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-3 text-left text-sm font-medium">Status</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Source</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Type</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Last Fetched</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Last Success</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Error</th>
                <th className="px-4 py-3 text-right text-sm font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sources.map((source) => (
                <tr key={source.id} className="hover:bg-muted/50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className={`h-2.5 w-2.5 rounded-full ${getStatusColor(source)}`} />
                      <span className="text-sm">{getStatusText(source)}</span>
                      {isPending(source) && (
                        <span className="px-1.5 py-0.5 text-xs rounded bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
                          Queued
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div>
                      <p className="font-medium">{source.name}</p>
                      <p className="text-sm text-muted-foreground">{source.city_id}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm">{source.source_type}</td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {formatTimeAgo(source.last_fetched_at)}
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {formatTimeAgo(source.last_success_at)}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {source.last_error ? (
                      <span className="text-red-600 truncate max-w-xs block" title={source.last_error}>
                        {source.last_error.substring(0, 40)}...
                      </span>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => triggerScrape(source.id)}
                      disabled={triggering !== null || isPending(source) || !source.is_enabled}
                      className="px-2.5 py-1 text-xs font-medium rounded bg-background border hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1"
                      title={
                        !source.is_enabled ? 'Source is disabled' :
                        isPending(source) ? 'Already queued' : 
                        `Run ${source.name}`
                      }
                    >
                      {triggering === source.id ? (
                        <svg className="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                      ) : (
                        <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                      )}
                      Run
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
