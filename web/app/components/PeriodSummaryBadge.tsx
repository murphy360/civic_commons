'use client';

import { useState, useTransition } from 'react';
import { prioritizePeriodicSummary } from '../actions/documents';

interface PeriodSummaryBadgeProps {
  /** The summary object if it exists */
  summary?: {
    id: number;
    status: string;
  } | null;
  /** Type of summary period */
  summaryType: 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'annual';
  /** Start date of the period (ISO string) */
  periodStart: string;
  /** Whether to show a compact inline badge vs the full clickable button */
  compact?: boolean;
}

/**
 * A clickable badge component for triggering (re)analysis of periodic summaries.
 * 
 * - If a completed summary exists: Shows "✨ AI Summary" badge, click to re-analyze
 * - If a pending/generating summary exists: Shows "⏳ Pending Analysis" badge, click to prioritize  
 * - If no summary exists: Shows "⏳ Pending Analysis" badge, click to create and queue
 */
export function PeriodSummaryBadge({ 
  summary, 
  summaryType,
  periodStart,
  compact = true
}: PeriodSummaryBadgeProps) {
  const [isPendingAction, startTransition] = useTransition();
  const [actionStatus, setActionStatus] = useState<'idle' | 'queued' | 'error'>('idle');
  
  const hasCompletedSummary = summary && summary.status === 'completed';
  const isPending = summary && (summary.status === 'pending' || summary.status === 'generating');
  const isGenerating = summary?.status === 'generating';
  const hasSummary = !!summary;

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    startTransition(async () => {
      let result;
      if (summary) {
        // Existing summary - queue for re-analysis
        result = await prioritizePeriodicSummary({ summaryId: summary.id });
      } else {
        // No summary exists - create and queue
        result = await prioritizePeriodicSummary({ summaryType, periodStart });
      }
      
      if (result.success) {
        setActionStatus('queued');
      } else {
        setActionStatus('error');
        setTimeout(() => setActionStatus('idle'), 3000);
      }
    });
  };

  // Queued state
  if (actionStatus === 'queued') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
        </svg>
        Queued
      </span>
    );
  }

  // Error state
  if (actionStatus === 'error') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-red-100 text-red-700">
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
        Error
      </span>
    );
  }

  // Loading state
  if (isPendingAction) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 opacity-50">
        <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        ...
      </span>
    );
  }

  // Completed summary
  if (hasCompletedSummary) {
    return (
      <button
        onClick={handleClick}
        disabled={isPendingAction}
        className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 hover:bg-purple-200 transition-colors cursor-pointer disabled:opacity-50"
        title="Click to re-analyze this summary"
      >
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        ✨ AI Summary
      </button>
    );
  }

  // Generating state (not clickable)
  if (isGenerating) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
        <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Generating...
      </span>
    );
  }

  // Pending state or no summary exists - show clickable pending badge
  return (
    <button
      onClick={handleClick}
      disabled={isPendingAction}
      className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors cursor-pointer disabled:opacity-50"
      title={hasSummary ? "Click to prioritize this summary" : "Click to queue this period for analysis"}
    >
      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      ⏳ Pending Analysis
    </button>
  );
}
