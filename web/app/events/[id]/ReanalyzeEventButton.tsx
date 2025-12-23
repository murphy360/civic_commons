'use client';

import { useState } from 'react';

interface ReanalyzeEventButtonProps {
  eventId: number;
}

export function ReanalyzeEventButton({ eventId }: ReanalyzeEventButtonProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleReanalyze = async () => {
    setIsLoading(true);
    setMessage(null);

    try {
      const response = await fetch('/api/events/reanalyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ eventId }),
      });

      if (!response.ok) {
        const error = await response.json();
        setMessage({
          type: 'error',
          text: error.error || 'Failed to queue event for re-analysis',
        });
        return;
      }

      const data = await response.json();
      setMessage({
        type: 'success',
        text: data.message || 'Event queued for re-analysis. This may take a few minutes.',
      });
    } catch (error) {
      setMessage({
        type: 'error',
        text: 'Error queuing event for re-analysis',
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
        className="inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-amber-100 text-amber-800 hover:bg-amber-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isLoading ? (
          <>
            <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            Processing...
          </>
        ) : (
          <>
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Re-analyze Event
          </>
        )}
      </button>

      {message && (
        <p className={`text-sm ${message.type === 'success' ? 'text-green-600' : 'text-red-600'}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
