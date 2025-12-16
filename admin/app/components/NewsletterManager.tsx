'use client';

import { useState, useCallback, useEffect } from 'react';

interface Newsletter {
  id: number;
  city_id: string;
  title: string;
  period_type: string;
  period_start: string;
  period_end: string;
  status: string;
  event_count: number;
  document_count: number;
  error_message: string | null;
  created_at: string;
}

interface Stats {
  total: number;
  completed: number;
  pending: number;
  failed: number;
}

const PERIOD_LABELS: Record<string, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  annual: 'Annual',
};

const PERIOD_COLORS: Record<string, string> = {
  daily: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  weekly: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  monthly: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  quarterly: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  annual: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
};

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-green-500',
  pending: 'bg-yellow-500',
  generating: 'bg-blue-500 animate-pulse',
  failed: 'bg-red-500',
};

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export default function NewsletterManager() {
  const [newsletters, setNewsletters] = useState<Newsletter[]>([]);
  const [stats, setStats] = useState<Stats>({ total: 0, completed: 0, pending: 0, failed: 0 });
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const fetchNewsletters = useCallback(async () => {
    try {
      const response = await fetch('/api/newsletters');
      if (!response.ok) throw new Error('Failed to fetch');
      const data = await response.json();
      setNewsletters(data.newsletters || []);
      setStats(data.stats || { total: 0, completed: 0, pending: 0, failed: 0 });
    } catch (error) {
      console.error('Failed to fetch newsletters:', error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNewsletters();
    // Refresh every 30 seconds to catch generation updates
    const interval = setInterval(fetchNewsletters, 30000);
    return () => clearInterval(interval);
  }, [fetchNewsletters]);

  const triggerGeneration = async (periodType: string) => {
    setGenerating(periodType);
    setMessage(null);

    try {
      const response = await fetch('/api/newsletters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ period_type: periodType }),
      });

      const data = await response.json();

      if (!response.ok) {
        setMessage({ type: 'error', text: data.error || 'Failed to generate' });
      } else {
        setMessage({ type: 'success', text: data.message });
        setTimeout(fetchNewsletters, 1000);
      }
    } catch (error) {
      console.error('Failed to trigger generation:', error);
      setMessage({ type: 'error', text: 'Failed to trigger generation' });
    } finally {
      setGenerating(null);
    }
  };

  // Auto-clear message after 5 seconds
  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [message]);

  return (
    <div className="rounded-lg border bg-card">
      <div className="flex items-center justify-between border-b p-4">
        <div className="flex items-center gap-4">
          <h2 className="font-semibold">Newsletter Management</h2>
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
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>{stats.completed} completed</span>
          <span>•</span>
          <span>{stats.pending} pending</span>
          {stats.failed > 0 && (
            <>
              <span>•</span>
              <span className="text-red-600">{stats.failed} failed</span>
            </>
          )}
        </div>
      </div>

      {/* Generation Buttons */}
      <div className="p-4 border-b bg-muted/30">
        <p className="text-sm text-muted-foreground mb-3">Generate Newsletter:</p>
        <div className="flex flex-wrap gap-2">
          {['daily', 'weekly', 'monthly', 'quarterly', 'annual'].map((type) => (
            <button
              key={type}
              onClick={() => triggerGeneration(type)}
              disabled={generating !== null}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${PERIOD_COLORS[type]} hover:opacity-80`}
            >
              {generating === type ? (
                <span className="flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Generating...
                </span>
              ) : (
                PERIOD_LABELS[type]
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Newsletter List */}
      {loading ? (
        <div className="p-8 text-center text-muted-foreground">
          Loading newsletters...
        </div>
      ) : newsletters.length === 0 ? (
        <div className="p-8 text-center text-muted-foreground">
          No newsletters generated yet. Click a button above to generate one.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-3 text-left text-sm font-medium">Status</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Title</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Period</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Coverage</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Stats</th>
                <th className="px-4 py-3 text-left text-sm font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {newsletters.map((newsletter) => (
                <tr key={newsletter.id} className="hover:bg-muted/50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className={`h-2.5 w-2.5 rounded-full ${STATUS_COLORS[newsletter.status]}`} />
                      <span className="text-sm capitalize">{newsletter.status}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-xs ${PERIOD_COLORS[newsletter.period_type]}`}>
                        {PERIOD_LABELS[newsletter.period_type]}
                      </span>
                      <span className="font-medium">{newsletter.title}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {formatDate(newsletter.period_start)} - {formatDate(newsletter.period_end)}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className="text-muted-foreground">
                      {newsletter.event_count} events, {newsletter.document_count} docs
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {newsletter.status === 'failed' && newsletter.error_message ? (
                      <span className="text-red-600" title={newsletter.error_message}>
                        Error
                      </span>
                    ) : (
                      formatDate(newsletter.created_at)
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {newsletter.status === 'completed' && (
                      <a
                        href={`http://localhost:3000/newsletters/${newsletter.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-primary hover:underline"
                      >
                        View →
                      </a>
                    )}
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
