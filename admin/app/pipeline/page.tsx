'use client';

import { useState, useEffect, useCallback } from 'react';
import Sidebar from '../components/Sidebar';
import { adminApi } from '@/lib/adminApi';

interface QueueStatus {
  download: {
    pending: number;
    in_progress: number;
    completed_today: number;
    failed_today: number;
    oldest_pending: string | null;
    newest_pending: string | null;
  };
  extraction: {
    pending: number;
    in_progress: number;
    completed_today: number;
    failed_today: number;
  };
  ai_documents: {
    pending: number;
    in_progress: number;
    completed_today: number;
    failed_today: number;
    failed_total: number;
    retrying: number;
  };
  ai_videos: {
    pending: number;
    in_progress: number;
    completed_today: number;
    failed_total: number;
    retrying: number;
  };
  ai_events: {
    pending: number;
    ready: number;
    blocked: number;
    completed_today: number;
  };
  ai_summaries: {
    pending: number;
    ready: number;
    blocked: number;
    in_progress: number;
    completed_today: number;
    failed_today: number;
  };
  linking: {
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
  };
  last_updated: string;
  total_pending: number;
  total_in_progress: number;
  is_healthy: boolean;
  health_message: string;
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

export default function PipelinePage() {
  const [status, setStatus] = useState<QueueStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await adminApi.getQueue();
      // Transform backend response to match interface
      const transformed = {
        download: data.download_queue,
        extraction: data.extraction_queue,
        ai_documents: data.ai_document_queue,
        ai_videos: data.ai_video_queue,
        ai_events: data.ai_event_queue,
        ai_summaries: data.ai_summary_queue,
        linking: data.linking_queue,
        last_updated: data.timestamp || new Date().toISOString(),
        total_pending: (data.download_queue?.pending || 0) + (data.extraction_queue?.pending || 0),
        total_in_progress: (data.download_queue?.in_progress || 0) + (data.extraction_queue?.in_progress || 0),
        is_healthy: data.health_status === 'healthy',
        health_message: data.health_status || 'unknown'
      };
      setStatus(transformed);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchStatus();
  }, []);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchStatus, 10000); // 10 seconds
    return () => clearInterval(interval);
  }, [autoRefresh, fetchStatus]);

  if (loading) {
    return (
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="max-w-7xl mx-auto">
            <div className="animate-pulse space-y-4">
              <div className="h-8 bg-gray-200 rounded w-1/4"></div>
              <div className="space-y-4">
                {[1, 2, 3].map(i => (
                  <div key={i} className="h-40 bg-gray-200 rounded"></div>
                ))}
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />

      {/* Main Content */}
      <main className="flex-1">
        {/* Header */}
        <header className="flex h-14 items-center justify-between border-b px-6">
          <h1 className="text-lg font-semibold">Processing Pipeline</h1>
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
            {status && (
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                status.is_healthy 
                  ? 'bg-green-100 text-green-700' 
                  : 'bg-red-100 text-red-700'
              }`}>
                {status.is_healthy ? '✓ Healthy' : '⚠ Issues'}
              </span>
            )}
          </div>
        </header>

        <div className="p-6 space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
            {error}
          </div>
        )}

        {/* Pipeline Overview */}
        {status && (
          <div className="bg-card border rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold">Pipeline Overview</h2>
              <span className="text-xs text-muted-foreground">
                Last updated: {formatRelativeTime(status.last_updated)}
              </span>
            </div>
            
            {/* Scraper Source */}
            <div className="flex justify-center mb-4">
              <div className="bg-slate-100 border border-slate-300 rounded-lg px-6 py-3 text-center">
                <div className="text-xl mb-1">🔍</div>
                <div className="font-medium text-sm">Scraper</div>
                <div className="text-xs text-muted-foreground">Discovers URLs & Creates Events</div>
              </div>
            </div>
            
            {/* Arrow down */}
            <div className="flex justify-center mb-4">
              <div className="text-2xl text-muted-foreground">↓</div>
            </div>

            {/* Three database tables */}
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-center">
                <div className="font-medium text-sm">📄 Documents</div>
                <div className="text-xs text-muted-foreground">PDFs & Videos</div>
              </div>
              <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-3 text-center">
                <div className="font-medium text-sm">📅 Events</div>
                <div className="text-xs text-muted-foreground">Meetings</div>
              </div>
              <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-center">
                <div className="font-medium text-sm">📊 Summaries</div>
                <div className="text-xs text-muted-foreground">Aggregated</div>
              </div>
            </div>

            {/* Divider */}
            <div className="border-t border-dashed my-6"></div>

            {/* Processing Priority Notice */}
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4">
              <div className="text-sm text-blue-800">
                <strong>⚡ Processing Priority:</strong> PDFs are processed before Videos to maximize event summaries
              </div>
            </div>

            {/* Two parallel paths */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              
              {/* PDF Path */}
              <div className="border rounded-lg p-4 bg-gradient-to-b from-blue-50/50 to-transparent">
                <div className="text-sm font-medium text-center mb-3 text-blue-800">
                  📄 PDF Pipeline (Agendas, Minutes, Legislation)
                  <span className="ml-2 text-xs bg-blue-100 px-2 py-0.5 rounded">Priority 1</span>
                </div>
                
                <div className="space-y-2">
                  {/* Discover */}
                  <div className="flex items-center gap-2">
                    <div className="flex-1 bg-white border rounded p-2 text-center">
                      <div className="text-xs text-muted-foreground">Discovered</div>
                      <div className="text-lg font-bold text-blue-600">{status.download.pending}</div>
                    </div>
                    <div className="text-muted-foreground">→</div>
                    <div className="flex-1 bg-white border rounded p-2 text-center">
                      <div className="text-xs text-muted-foreground">Downloaded</div>
                      <div className="text-lg font-bold text-cyan-600">{status.extraction.pending}</div>
                      {status.download.in_progress > 0 && (
                        <div className="text-xs text-cyan-500">{status.download.in_progress} active</div>
                      )}
                    </div>
                  </div>
                  
                  <div className="flex justify-center text-muted-foreground">↓</div>
                  
                  {/* Extract & AI */}
                  <div className="flex items-center gap-2">
                    <div className="flex-1 bg-white border rounded p-2 text-center">
                      <div className="text-xs text-muted-foreground">Extracted</div>
                      <div className="text-lg font-bold text-purple-600">{status.ai_documents.pending}</div>
                      {status.extraction.in_progress > 0 && (
                        <div className="text-xs text-purple-500">{status.extraction.in_progress} active</div>
                      )}
                    </div>
                    <div className="text-muted-foreground">→</div>
                    <div className="flex-1 bg-white border rounded p-2 text-center border-orange-300 bg-orange-50">
                      <div className="text-xs text-orange-700">AI Summary</div>
                      <div className="text-lg font-bold text-orange-600">🤖</div>
                      {status.ai_documents.in_progress > 0 && (
                        <div className="text-xs text-orange-500">{status.ai_documents.in_progress} active</div>
                      )}
                      <div className="text-xs text-green-600">+{status.ai_documents.completed_today}</div>
                      {status.ai_documents.failed_total > 0 && (
                        <div className="text-xs text-red-600 mt-1">🚫 {status.ai_documents.failed_total} failed</div>
                      )}
                      {status.ai_documents.retrying > 0 && (
                        <div className="text-xs text-yellow-600">⚠️ {status.ai_documents.retrying} retrying</div>
                      )}
                    </div>
                  </div>
                </div>
                
                <div className="mt-3 pt-2 border-t text-xs text-center text-muted-foreground">
                  +{status.download.completed_today} downloaded, +{status.extraction.completed_today} extracted today
                </div>
              </div>

              {/* Video Path */}
              <div className="border rounded-lg p-4 bg-gradient-to-b from-pink-50/50 to-transparent">
                <div className="text-sm font-medium text-center mb-3 text-pink-800">
                  🎬 Video Pipeline (YouTube)
                  <span className="ml-2 text-xs bg-pink-100 px-2 py-0.5 rounded">Priority 2</span>
                </div>
                
                <div className="space-y-2">
                  {/* Discover → Parse Date → AI */}
                  <div className="flex items-center gap-2">
                    <div className="flex-1 bg-white border rounded p-2 text-center">
                      <div className="text-xs text-muted-foreground">Discovered</div>
                      <div className="text-lg font-bold text-pink-600">{status.ai_videos.pending}</div>
                    </div>
                    <div className="text-muted-foreground">→</div>
                    <div className="flex-1 bg-white border rounded p-2 text-center border-cyan-300 bg-cyan-50">
                      <div className="text-xs text-cyan-700">📅 Parse Date</div>
                      <div className="text-sm font-bold text-cyan-600">
                        {status.linking?.videos_with_date || 0}/{status.linking?.total_videos || 0}
                      </div>
                      <div className="text-[10px] text-cyan-600">from title</div>
                    </div>
                    <div className="text-muted-foreground">→</div>
                    <div className="flex-1 bg-white border rounded p-2 text-center border-orange-300 bg-orange-50">
                      <div className="text-xs text-orange-700">AI Transcribe</div>
                      <div className="text-lg font-bold text-orange-600">🤖</div>
                      {status.ai_videos.in_progress > 0 && (
                        <div className="text-xs text-pink-500">{status.ai_videos.in_progress} active</div>
                      )}
                      <div className="text-xs text-green-600">+{status.ai_videos.completed_today}</div>
                      {status.ai_videos.failed_total > 0 && (
                        <div className="text-xs text-red-600 mt-1">🚫 {status.ai_videos.failed_total} failed</div>
                      )}
                      {status.ai_videos.retrying > 0 && (
                        <div className="text-xs text-yellow-600">⚠️ {status.ai_videos.retrying} retrying</div>
                      )}
                    </div>
                  </div>
                  
                  <div className="bg-amber-50 border border-amber-200 rounded p-2 text-center text-xs text-amber-700 mt-2">
                    ⚡ No download needed - uses YouTube API for transcription
                  </div>
                </div>
                
                <div className="mt-3 pt-2 border-t text-xs text-center text-muted-foreground">
                  Videos wait for PDFs to complete first
                </div>
              </div>
            </div>

            {/* Document → Event Linking Section */}
            <div className="border rounded-lg p-4 mt-6 bg-gradient-to-r from-blue-50/30 via-indigo-50/30 to-pink-50/30">
              <div className="text-sm font-medium text-center mb-4 text-gray-700">
                🔗 Content → Event Linking
              </div>
              
              {/* Meeting Documents Row */}
              <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 mb-4">
                {/* Agendas */}
                <div className="bg-white border rounded-lg p-3">
                  <div className="text-xs font-medium text-blue-700 mb-2 text-center">📋 Agendas</div>
                  <div className="text-center">
                    <div className="text-lg font-bold text-green-600">
                      {status.linking?.agendas_linked || 0}
                      <span className="text-sm text-gray-400">/{status.linking?.agendas_total || 0}</span>
                    </div>
                    <div className="text-[10px] text-green-700">linked to events</div>
                  </div>
                </div>

                {/* Minutes */}
                <div className="bg-white border rounded-lg p-3">
                  <div className="text-xs font-medium text-blue-700 mb-2 text-center">📝 Minutes</div>
                  <div className="text-center">
                    <div className="text-lg font-bold text-green-600">
                      {status.linking?.minutes_linked || 0}
                      <span className="text-sm text-gray-400">/{status.linking?.minutes_total || 0}</span>
                    </div>
                    <div className="text-[10px] text-green-700">linked to events</div>
                  </div>
                </div>

                {/* Videos */}
                <div className="bg-white border rounded-lg p-3">
                  <div className="text-xs font-medium text-pink-700 mb-2 text-center">🎬 Videos</div>
                  <div className="text-center">
                    <div className="text-lg font-bold text-green-600">
                      {status.linking?.videos_linked || 0}
                      <span className="text-sm text-gray-400">/{status.linking?.total_videos || 0}</span>
                    </div>
                    <div className="text-[10px] text-green-700">linked to events</div>
                    <div className="text-[10px] text-amber-600 mt-1">
                      {status.linking?.videos_with_date || 0} have dates parsed
                    </div>
                  </div>
                </div>

                {/* Linking to Events */}
                <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-3 flex flex-col justify-center">
                  <div className="text-xs font-medium text-indigo-700 mb-1 text-center">📅 Events</div>
                  <div className="text-[10px] text-center text-indigo-600">
                    Linked via:<br/>
                    • meeting_date match<br/>
                    • source + committee<br/>
                    • AI title matching
                  </div>
                </div>
              </div>

              {/* Legislation Row */}
              <div className="border-t pt-4">
                <div className="text-xs font-medium text-center mb-3 text-gray-600">
                  📜 Legislation Tracking
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
                  {/* Ordinances */}
                  <div className="bg-white border rounded-lg p-3">
                    <div className="text-xs font-medium text-amber-700 mb-2 text-center">📜 Ordinances</div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-amber-600">{status.linking?.ordinances_total || 0}</div>
                      <div className="text-[10px] text-amber-700">total tracked</div>
                    </div>
                  </div>

                  {/* Resolutions */}
                  <div className="bg-white border rounded-lg p-3">
                    <div className="text-xs font-medium text-amber-700 mb-2 text-center">📜 Resolutions</div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-amber-600">{status.linking?.resolutions_total || 0}</div>
                      <div className="text-[10px] text-amber-700">total tracked</div>
                    </div>
                  </div>

                  {/* Legislation Mentions */}
                  <div className="bg-white border rounded-lg p-3">
                    <div className="text-xs font-medium text-amber-700 mb-2 text-center">🔍 Mentions Found</div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-amber-600">{status.linking?.legislation_mentions || 0}</div>
                      <div className="text-[10px] text-amber-700">in documents</div>
                    </div>
                  </div>

                  {/* Linked to Events */}
                  <div className="bg-white border rounded-lg p-3">
                    <div className="text-xs font-medium text-green-700 mb-2 text-center">✓ Linked</div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-green-600">{status.linking?.legislation_linked_events || 0}</div>
                      <div className="text-[10px] text-green-700">to events</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Event Summary Tiers */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
              {/* Event AI Summaries */}
              <div className="border rounded-lg p-4 bg-gradient-to-b from-indigo-50/50 to-transparent">
                <div className="text-sm font-medium text-center mb-3 text-indigo-800">
                  📅 Event AI Summaries
                  <span className="ml-2 text-xs bg-indigo-100 px-2 py-0.5 rounded">Tier 2</span>
                </div>
                <div className="text-center">
                  <div className="text-xs text-muted-foreground mb-2">Combines all doc + video summaries for each meeting</div>
                  <div className="flex justify-center gap-6 my-3">
                    <div className="bg-green-50 border border-green-200 rounded-lg p-3 min-w-[80px]">
                      <div className="text-2xl font-bold text-green-600">{status.ai_events.ready || 0}</div>
                      <div className="text-xs text-green-700 font-medium">Ready</div>
                      <div className="text-[10px] text-green-600">All docs summarized</div>
                    </div>
                    <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 min-w-[80px]">
                      <div className="text-2xl font-bold text-amber-600">{status.ai_events.blocked || 0}</div>
                      <div className="text-xs text-amber-700 font-medium">Blocked</div>
                      <div className="text-[10px] text-amber-600">Waiting on docs</div>
                    </div>
                  </div>
                  {status.ai_events.blocked > 0 && (
                    <div className="text-xs text-amber-700 bg-amber-50 rounded px-2 py-1 inline-block">
                      ⏳ {status.ai_events.blocked} events waiting for their documents to be summarized
                    </div>
                  )}
                  <div className="text-xs text-green-600 mt-3">+{status.ai_events.completed_today} completed today</div>
                </div>
              </div>

              {/* Periodic Summaries */}
              <div className="border rounded-lg p-4 bg-gradient-to-b from-emerald-50/50 to-transparent">
                <div className="text-sm font-medium text-center mb-3 text-emerald-800">
                  📊 Periodic Summaries
                  <span className="ml-2 text-xs bg-emerald-100 px-2 py-0.5 rounded">Tier 3</span>
                </div>
                <div className="text-xs text-muted-foreground mb-2 text-center">Aggregates event summaries by time period</div>
                <div className="grid grid-cols-5 gap-1 text-center text-xs mb-3">
                  <div className="bg-white border rounded p-1">
                    <div className="text-muted-foreground">Daily</div>
                  </div>
                  <div className="bg-white border rounded p-1">
                    <div className="text-muted-foreground">Weekly</div>
                  </div>
                  <div className="bg-white border rounded p-1">
                    <div className="text-muted-foreground">Monthly</div>
                  </div>
                  <div className="bg-white border rounded p-1">
                    <div className="text-muted-foreground">Quarterly</div>
                  </div>
                  <div className="bg-white border rounded p-1">
                    <div className="text-muted-foreground">Annual</div>
                  </div>
                </div>
                <div className="flex justify-center gap-6 my-3">
                  <div className="bg-green-50 border border-green-200 rounded-lg p-3 min-w-[80px] text-center">
                    <div className="text-2xl font-bold text-green-600">{status.ai_summaries.ready || 0}</div>
                    <div className="text-xs text-green-700 font-medium">Ready</div>
                    <div className="text-[10px] text-green-600">All events done</div>
                  </div>
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 min-w-[80px] text-center">
                    <div className="text-2xl font-bold text-amber-600">{status.ai_summaries.blocked || 0}</div>
                    <div className="text-xs text-amber-700 font-medium">Blocked</div>
                    <div className="text-[10px] text-amber-600">Waiting on events</div>
                  </div>
                </div>
                {status.ai_summaries.in_progress > 0 && (
                  <div className="text-xs text-emerald-600 text-center mb-2">🔄 {status.ai_summaries.in_progress} generating now</div>
                )}
                <div className="text-xs text-green-600 text-center">+{status.ai_summaries.completed_today} completed today</div>
              </div>
            </div>

            {/* Summary Stats Bar */}
            <div className="mt-6 pt-4 border-t flex items-center justify-between">
              <div className="flex gap-6 text-sm">
                <span>
                  <strong>{status.total_pending}</strong> total pending
                </span>
                <span>
                  <strong>{status.total_in_progress}</strong> in progress
                </span>
              </div>
              <div className="flex items-center gap-2">
                {(status.download.failed_today || 0) + 
                 (status.extraction.failed_today || 0) + 
                 (status.ai_documents.failed_today || 0) +
                 (status.ai_summaries.failed_today || 0) > 0 && (
                  <span className="text-sm text-red-600">
                    ⚠️ {(status.download.failed_today || 0) + 
                        (status.extraction.failed_today || 0) + 
                        (status.ai_documents.failed_today || 0) +
                        (status.ai_summaries.failed_today || 0)} failed today
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
        </div>
      </main>
    </div>
  );
}
