'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';

interface AutoRefreshProps {
  children: React.ReactNode;
  intervalSeconds?: number;
}

export default function AutoRefresh({ children, intervalSeconds = 30 }: AutoRefreshProps) {
  const router = useRouter();
  const [isEnabled, setIsEnabled] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(new Date());
  const [countdown, setCountdown] = useState(intervalSeconds);

  const refresh = useCallback(() => {
    router.refresh();
    setLastRefresh(new Date());
    setCountdown(intervalSeconds);
  }, [router, intervalSeconds]);

  // Auto-refresh timer
  useEffect(() => {
    if (!isEnabled) return;

    const countdownInterval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          refresh();
          return intervalSeconds;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(countdownInterval);
  }, [isEnabled, intervalSeconds, refresh]);

  return (
    <div>
      {/* Auto-refresh control bar */}
      <div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 bg-card border rounded-lg shadow-lg px-4 py-2">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsEnabled(!isEnabled)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              isEnabled ? 'bg-green-500' : 'bg-gray-300'
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                isEnabled ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
          <span className="text-sm text-muted-foreground">
            Auto-refresh
          </span>
        </div>
        
        {isEnabled && (
          <span className="text-sm text-muted-foreground tabular-nums">
            {countdown}s
          </span>
        )}
        
        <button
          onClick={refresh}
          className="p-1.5 rounded hover:bg-muted transition-colors"
          title="Refresh now"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
        
        <span className="text-xs text-muted-foreground border-l pl-3">
          Updated: {lastRefresh.toLocaleTimeString()}
        </span>
      </div>
      
      {children}
    </div>
  );
}
