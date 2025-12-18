'use client';

import { useState, useTransition } from 'react';
import { reprocessDocument } from '../actions/documents';

interface LinkStatusBadgeProps {
  documentId: number;
  eventCount: number;
  linkedLabel?: string;
  variant?: 'default' | 'compact';
}

export function LinkStatusBadge({ 
  documentId, 
  eventCount,
  linkedLabel,
  variant = 'default'
}: LinkStatusBadgeProps) {
  const [isPending, startTransition] = useTransition();
  const [status, setStatus] = useState<'idle' | 'queued' | 'error'>('idle');

  if (eventCount > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-emerald-100 text-emerald-800">
        {variant === 'compact' ? (
          <>✓ {linkedLabel || `${eventCount} event${eventCount !== 1 ? 's' : ''}`}</>
        ) : (
          <>
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            {linkedLabel || `${eventCount} event${eventCount !== 1 ? 's' : ''}`}
          </>
        )}
      </span>
    );
  }

  if (status === 'queued') {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-blue-100 text-blue-700">
        <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Queued
      </span>
    );
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    startTransition(async () => {
      const result = await reprocessDocument(documentId);
      if (result.success) {
        setStatus('queued');
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
      className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-amber-100 text-amber-800 hover:bg-amber-200 transition-colors cursor-pointer disabled:opacity-50"
      title="Click to queue for re-linking"
    >
      {isPending ? (
        <svg className="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
      ) : status === 'error' ? (
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      ) : null}
      {status === 'error' ? 'Failed' : 'Unlinked'}
    </button>
  );
}
