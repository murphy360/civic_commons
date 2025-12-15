'use client';

interface AISummarySectionProps {
  eventId: number;
  summary: string | null;
  updatedAt: Date | null;
  hasDocuments: boolean;
}

export function AISummarySection({ eventId, summary, updatedAt, hasDocuments }: AISummarySectionProps) {
  // Format the updated date
  const formatUpdatedAt = (date: Date | null) => {
    if (!date) return null;
    return new Date(date).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  // Don't show section if no summary and no documents
  if (!summary && !hasDocuments) {
    return null;
  }

  return (
    <div className="mt-6 p-6 rounded-lg bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <svg className="h-5 w-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          <h3 className="text-lg font-semibold text-blue-900">AI Overview</h3>
        </div>
        {updatedAt && summary && (
          <span className="text-xs text-blue-600">
            Updated {formatUpdatedAt(updatedAt)}
          </span>
        )}
      </div>
      
      {summary ? (
        <div className="prose prose-sm max-w-none text-blue-900">
          <div className="whitespace-pre-wrap">{summary}</div>
        </div>
      ) : (
        <div className="text-blue-800">
          <p className="text-sm text-blue-600 italic">
            AI summary is being generated and will appear here once processing is complete.
          </p>
        </div>
      )}
    </div>
  );
}
