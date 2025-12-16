'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';

interface Event {
  id: number;
  title: string;
  description: string | null;
  start_time: string;
  end_time: string | null;
  location: string | null;
  source_url: string | null;
  video_url: string | null;
  source_names: string;
  source_count: number;
  document_count: number;
  has_agenda: number;
  has_minutes: number;
  first_doc_id: number | null;
  has_ai_summary: boolean;
}

interface MonthGroup {
  key: string;
  label: string;
  events: Event[];
}

function formatDate(date: string): string {
  return new Date(date).toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function formatTime(date: string): string {
  return new Date(date).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function getMonthKey(date: string): string {
  const d = new Date(date);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function getMonthLabel(date: string): string {
  return new Date(date).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
  });
}

function groupEventsByMonth(events: Event[]): MonthGroup[] {
  const groups: Map<string, Event[]> = new Map();
  
  for (const event of events) {
    const key = getMonthKey(event.start_time);
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(event);
  }
  
  // Convert to array and sort by key (most recent first)
  return Array.from(groups.entries())
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([key, events]) => ({
      key,
      label: getMonthLabel(events[0].start_time),
      events,
    }));
}

function EventCard({ event }: { event: Event }) {
  const sources = event.source_names ? event.source_names.split(', ') : [];
  const docLink = event.document_count === 1 && event.first_doc_id 
    ? `/documents/${event.first_doc_id}`
    : `/events/${event.id}#documents`;
  
  return (
    <div className="block border rounded-lg p-6 hover:border-primary/50 transition-colors bg-muted/30">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
        <Link href={`/events/${event.id}`} className="flex-1">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            {sources.map((source, idx) => (
              <span 
                key={idx}
                className="text-xs font-medium px-2 py-1 rounded-full bg-primary/10 text-primary"
              >
                {source}
              </span>
            ))}
            {event.source_count > 1 && (
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-emerald-100 text-emerald-800" title="Verified across multiple sources">
                ✓ {event.source_count} sources
              </span>
            )}
            <span className="text-xs font-medium px-2 py-1 rounded-full bg-gray-100 text-gray-600">
              Past
            </span>
            {event.has_agenda > 0 && (
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-green-100 text-green-800">
                Agenda
              </span>
            )}
            {event.has_minutes > 0 && (
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-blue-100 text-blue-800">
                Minutes
              </span>
            )}
            {event.video_url && (
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-red-100 text-red-800">
                📹 Video
              </span>
            )}
            {event.has_ai_summary && (
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-indigo-100 text-indigo-800" title="AI Overview Available">
                ✨ AI Overview
              </span>
            )}
          </div>
          <h2 className="text-xl font-semibold mb-2 text-muted-foreground">
            {event.title}
          </h2>
          {event.description && (
            <p className="text-muted-foreground mb-4 line-clamp-2">
              {event.description}
            </p>
          )}
          <div className="flex flex-col gap-1 text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span>{formatDate(event.start_time)}</span>
            </div>
            <div className="flex items-center gap-2">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>
                {formatTime(event.start_time)}
                {event.end_time && ` - ${formatTime(event.end_time)}`}
              </span>
            </div>
            {event.location && (
              <div className="flex items-center gap-2">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <span>{event.location}</span>
              </div>
            )}
          </div>
        </Link>
        {event.document_count > 0 && (
          <Link 
            href={docLink}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 transition-colors text-sm font-medium self-end md:self-start"
            title={`View ${event.document_count} document${event.document_count !== 1 ? 's' : ''}`}
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <span>{event.document_count} Doc{event.document_count !== 1 ? 's' : ''}</span>
            <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        )}
      </div>
    </div>
  );
}

function MonthGroupSection({ 
  group, 
  isExpanded, 
  onToggle 
}: { 
  group: MonthGroup; 
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 bg-muted/50 hover:bg-muted/70 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <svg 
            className={`h-5 w-5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} 
            fill="none" 
            stroke="currentColor" 
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="font-semibold text-lg">{group.label}</span>
        </div>
        <span className="text-sm text-muted-foreground bg-background px-3 py-1 rounded-full">
          {group.events.length} event{group.events.length !== 1 ? 's' : ''}
        </span>
      </button>
      
      {isExpanded && (
        <div className="p-4 space-y-4 bg-background">
          {group.events.map((event) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

interface PastEventsSectionProps {
  initialEvents: Event[];
  totalCount: number;
}

export default function PastEventsSection({ initialEvents, totalCount }: PastEventsSectionProps) {
  const [events, setEvents] = useState<Event[]>(initialEvents);
  const [expandedMonths, setExpandedMonths] = useState<Set<string>>(() => {
    // Expand the most recent month by default
    if (initialEvents.length > 0) {
      const firstKey = getMonthKey(initialEvents[0].start_time);
      return new Set([firstKey]);
    }
    return new Set();
  });
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(initialEvents.length < totalCount);
  
  const monthGroups = groupEventsByMonth(events);
  
  const toggleMonth = useCallback((key: string) => {
    setExpandedMonths(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);
  
  const loadMore = useCallback(async () => {
    if (loading || !hasMore) return;
    
    setLoading(true);
    try {
      const offset = events.length;
      const response = await fetch(`/api/events/past?offset=${offset}&limit=50`);
      if (!response.ok) throw new Error('Failed to load events');
      
      const data = await response.json();
      const newEvents: Event[] = data.events;
      
      if (newEvents.length === 0) {
        setHasMore(false);
      } else {
        setEvents(prev => [...prev, ...newEvents]);
        setHasMore(events.length + newEvents.length < data.total);
      }
    } catch (error) {
      console.error('Failed to load more events:', error);
    } finally {
      setLoading(false);
    }
  }, [events.length, loading, hasMore]);
  
  const expandAll = useCallback(() => {
    setExpandedMonths(new Set(monthGroups.map(g => g.key)));
  }, [monthGroups]);
  
  const collapseAll = useCallback(() => {
    setExpandedMonths(new Set());
  }, []);
  
  if (events.length === 0) {
    return null;
  }
  
  return (
    <section>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-muted-foreground">
          Past Events
          <span className="text-sm font-normal ml-2">
            ({events.length}{hasMore ? `+ of ${totalCount}` : ''})
          </span>
        </h2>
        <div className="flex gap-2">
          <button
            onClick={expandAll}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors px-2 py-1"
          >
            Expand All
          </button>
          <span className="text-muted-foreground">|</span>
          <button
            onClick={collapseAll}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors px-2 py-1"
          >
            Collapse All
          </button>
        </div>
      </div>
      
      <div className="space-y-4">
        {monthGroups.map((group) => (
          <MonthGroupSection
            key={group.key}
            group={group}
            isExpanded={expandedMonths.has(group.key)}
            onToggle={() => toggleMonth(group.key)}
          />
        ))}
      </div>
      
      {hasMore && (
        <div className="mt-8 text-center">
          <button
            onClick={loadMore}
            disabled={loading}
            className="px-6 py-3 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Loading...
              </span>
            ) : (
              `Load More Events (${totalCount - events.length} remaining)`
            )}
          </button>
        </div>
      )}
    </section>
  );
}
