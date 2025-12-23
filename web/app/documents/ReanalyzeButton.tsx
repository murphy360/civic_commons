'use client';

import { useState } from 'react';

interface ReanalyzeButtonProps {
  documentId: number;
}

export function ReanalyzeButton({ documentId }: ReanalyzeButtonProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleReanalyze = async () => {
    setIsLoading(true);
    setMessage(null);

    try {
      const response = await fetch('/api/documents/reanalyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ documentId }),
      });

      if (!response.ok) {
        const error = await response.json();
        setMessage({
          type: 'error',
          text: error.error || 'Failed to queue document for re-analysis',
        });
        return;
      }

      setMessage({
        type: 'success',
        text: 'Document queued for re-analysis. This may take a few minutes.',
      });
    } catch (error) {
      setMessage({
        type: 'error',
        text: 'Error queuing document for re-analysis',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <button
        onClick={handleReanalyze}
        disabled={isLoading}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-amber-100 text-amber-800 hover:bg-amber-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        {isLoading ? 'Queuing...' : 'Re-analyze Document'}
      </button>
      {message && (
        <div className={`text-sm p-3 rounded-md ${
          message.type === 'success'
            ? 'bg-green-50 text-green-800 border border-green-200'
            : 'bg-red-50 text-red-800 border border-red-200'
        }`}>
          {message.text}
        </div>
      )}
    </div>
  );
}
