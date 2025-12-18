'use client';

import { useState, useTransition } from 'react';
import { prioritizeSummary } from '../actions/documents';

interface AISummaryBadgeProps {
  documentId: number;
  hasSummary: boolean;
  /** Whether this document is eligible for summarization (has local_path or is YouTube video) */
  canSummarize?: boolean;
}

export function AISummaryBadge({ 
  documentId, 
  hasSummary,
  canSummarize = true
}: AISummaryBadgeProps) {
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState<'idle' | 'prioritized' | 'error'>('idle');

  // If already has summary, show the completed badge
  if (hasSummary) {
    return (
      <span 
        className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-indigo-100 text-indigo-800"
        title="AI Summary Available"
      >
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        ✨ AI Summary
      </span>
    );
  }

  // Can't summarize this document type
  if (!canSummarize) {
    return null;
  }

  // Just prioritized
  if (status === 'prioritized') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-blue-100 text-blue-700">
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
        </svg>
        Prioritized
      </span>
    );
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    startTransition(async () => {
      const result = await prioritizeSummary(documentId);
      if (result.success) {
        setStatus('prioritized');
      } else {
        setStatus('error');
        setTimeout(() => setStatus('idle'), 3000);
      }
    });
  };

  return (
    <button
      onClick={handleClick}
      disabled={isPending}
      className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-gray-100 text-gray-600 hover:bg-indigo-100 hover:text-indigo-700 transition-colors cursor-pointer disabled:opacity-50"
      title="Click to prioritize AI summary"
    >
      {isPending ? (
        <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
      ) : status === 'error' ? (
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      ) : (
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      )}
      {status === 'error' ? 'Error' : 'Pending Summary'}
    </button>
  );
}
