'use client';

import { useState, useCallback, useMemo } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';
import EventFilters, { type FilterState } from './EventFilters';

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

interface Summary {
  id: number;
  title: string | null;
  summary_type: string;
  period_start: string;
  period_end: string;
  summary_text: string | null;
  status: string;
  model_used: string | null;
}

interface WeekGroup {
  key: string;
  label: string;
  startDate: Date;
  endDate: Date;
  events: Event[];
  summary: Summary | null;
}

interface MonthGroup {
  key: string;
  label: string;
  monthName: string;
  events: Event[];
  summary: Summary | null;
  weeks: WeekGroup[];
}

interface QuarterGroup {
  key: string;
  label: string;
  quarter: number;
  year: number;
  events: Event[];
  summary: Summary | null;
  months: MonthGroup[];
}

interface YearGroup {
  key: string;
  year: number;
  events: Event[];
  summary: Summary | null;
  quarters: QuarterGroup[];
}

interface EventsPageClientProps {
  upcomingEvents: Event[];
  pastEvents: Event[];
  pastTotalCount: number;
  availableSources: string[];
  summaries: Summary[];
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

function getWeekKey(date: string): string {
  const d = new Date(date);
  // Get the Monday of this week
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1); // Adjust for Sunday
  const monday = new Date(d.setDate(diff));
  return monday.toISOString().split('T')[0];
}

function getWeekRange(date: string): { start: Date; end: Date; label: string } {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  const monday = new Date(d);
  monday.setDate(diff);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  
  const options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' };
  const label = `${monday.toLocaleDateString('en-US', options)} - ${sunday.toLocaleDateString('en-US', options)}`;
  
  return { start: monday, end: sunday, label };
}

function getQuarterFromMonth(month: number): number {
  return Math.ceil((month + 1) / 3);
}

function getQuarterKey(date: string): string {
  const d = new Date(date);
  return `${d.getFullYear()}-Q${getQuarterFromMonth(d.getMonth())}`;
}

function getYearKey(date: string): string {
  return new Date(date).getFullYear().toString();
}

function groupEventsHierarchically(events: Event[], summaries: Summary[]): YearGroup[] {
  // Index summaries by type and period
  const annualSummaries = new Map<string, Summary>();
  const quarterlySummaries = new Map<string, Summary>();
  const monthlySummaries = new Map<string, Summary>();
  const weeklySummaries = new Map<string, Summary>();
  
  for (const summary of summaries) {
    const periodStart = new Date(summary.period_start);
    if (summary.summary_type === 'annual') {
      annualSummaries.set(periodStart.getFullYear().toString(), summary);
    } else if (summary.summary_type === 'quarterly') {
      const key = `${periodStart.getFullYear()}-Q${getQuarterFromMonth(periodStart.getMonth())}`;
      quarterlySummaries.set(key, summary);
    } else if (summary.summary_type === 'monthly') {
      const key = `${periodStart.getFullYear()}-${String(periodStart.getMonth() + 1).padStart(2, '0')}`;
      monthlySummaries.set(key, summary);
    } else if (summary.summary_type === 'weekly') {
      const key = periodStart.toISOString().split('T')[0];
      weeklySummaries.set(key, summary);
    }
  }
  
  // Build hierarchical structure
  const yearMap = new Map<string, {
    events: Event[];
    quarterMap: Map<string, {
      events: Event[];
      monthMap: Map<string, {
        events: Event[];
        weekMap: Map<string, Event[]>;
      }>;
    }>;
  }>();
  
  for (const event of events) {
    const yearKey = getYearKey(event.start_time);
    const quarterKey = getQuarterKey(event.start_time);
    const monthKey = getMonthKey(event.start_time);
    const weekKey = getWeekKey(event.start_time);
    
    if (!yearMap.has(yearKey)) {
      yearMap.set(yearKey, { events: [], quarterMap: new Map() });
    }
    const yearData = yearMap.get(yearKey)!;
    yearData.events.push(event);
    
    if (!yearData.quarterMap.has(quarterKey)) {
      yearData.quarterMap.set(quarterKey, { events: [], monthMap: new Map() });
    }
    const quarterData = yearData.quarterMap.get(quarterKey)!;
    quarterData.events.push(event);
    
    if (!quarterData.monthMap.has(monthKey)) {
      quarterData.monthMap.set(monthKey, { events: [], weekMap: new Map() });
    }
    const monthData = quarterData.monthMap.get(monthKey)!;
    monthData.events.push(event);
    
    if (!monthData.weekMap.has(weekKey)) {
      monthData.weekMap.set(weekKey, []);
    }
    monthData.weekMap.get(weekKey)!.push(event);
  }
  
  // Convert to array structure
  return Array.from(yearMap.entries())
    .sort((a, b) => b[0].localeCompare(a[0]))
    .map(([yearKey, yearData]) => {
      const year = parseInt(yearKey);
      
      const quarters: QuarterGroup[] = Array.from(yearData.quarterMap.entries())
        .sort((a, b) => b[0].localeCompare(a[0]))
        .map(([qKey, qData]) => {
          const quarter = parseInt(qKey.split('-Q')[1]);
          
          const months: MonthGroup[] = Array.from(qData.monthMap.entries())
            .sort((a, b) => b[0].localeCompare(a[0]))
            .map(([mKey, mData]) => {
              const weeks: WeekGroup[] = Array.from(mData.weekMap.entries())
                .sort((a, b) => b[0].localeCompare(a[0]))
                .map(([wKey, wEvents]) => {
                  const weekRange = getWeekRange(wEvents[0].start_time);
                  return {
                    key: wKey,
                    label: weekRange.label,
                    startDate: weekRange.start,
                    endDate: weekRange.end,
                    events: wEvents.sort((a, b) => 
                      new Date(b.start_time).getTime() - new Date(a.start_time).getTime()
                    ),
                    summary: weeklySummaries.get(wKey) || null,
                  };
                });
              
              const firstEvent = mData.events[0];
              const monthDate = new Date(firstEvent.start_time);
              
              return {
                key: mKey,
                label: getMonthLabel(firstEvent.start_time),
                monthName: monthDate.toLocaleDateString('en-US', { month: 'long' }),
                events: mData.events,
                summary: monthlySummaries.get(mKey) || null,
                weeks,
              };
            });
          
          return {
            key: qKey,
            label: `Q${quarter} ${year}`,
            quarter,
            year,
            events: qData.events,
            summary: quarterlySummaries.get(qKey) || null,
            months,
          };
        });
      
      return {
        key: yearKey,
        year,
        events: yearData.events,
        summary: annualSummaries.get(yearKey) || null,
        quarters,
      };
    });
}

// groupEventsByMonthWithSummaries is replaced by groupEventsHierarchically

// Helper to check if event matches filters
function eventMatchesFilters(event: Event, filters: FilterState, isUpcoming: boolean): boolean {
  // Search filter
  if (filters.search) {
    const searchLower = filters.search.toLowerCase();
    const titleMatch = event.title.toLowerCase().includes(searchLower);
    const descMatch = event.description?.toLowerCase().includes(searchLower);
    const sourceMatch = event.source_names.toLowerCase().includes(searchLower);
    if (!titleMatch && !descMatch && !sourceMatch) return false;
  }
  
  // Source filter
  if (filters.sources.length > 0) {
    const eventSources = event.source_names.split(', ');
    const hasMatchingSource = eventSources.some(s => filters.sources.includes(s));
    if (!hasMatchingSource) return false;
  }
  
  // Document filter
  if (filters.hasDocuments === true && event.document_count === 0) return false;
  
  // Video filter
  if (filters.hasVideo === true && !event.video_url) return false;
  
  // AI Summary filter
  if (filters.hasAISummary === true && !event.has_ai_summary) return false;
  
  // Date range filter (only applies to past events)
  if (!isUpcoming && filters.dateRange !== 'all') {
    const eventDate = new Date(event.start_time);
    const now = new Date();
    let cutoffDate: Date;
    
    switch (filters.dateRange) {
      case '7days':
        cutoffDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        break;
      case '30days':
        cutoffDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
        break;
      case '90days':
        cutoffDate = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
        break;
      case 'year':
        cutoffDate = new Date(now.getTime() - 365 * 24 * 60 * 60 * 1000);
        break;
      default:
        cutoffDate = new Date(0);
    }
    
    if (eventDate < cutoffDate) return false;
  }
  
  return true;
}

function EventCard({ event, isPast = false }: { event: Event; isPast?: boolean }) {
  const sources = event.source_names ? event.source_names.split(', ') : [];
  const docLink = event.document_count === 1 && event.first_doc_id 
    ? `/documents/${event.first_doc_id}`
    : `/events/${event.id}#documents`;
  
  return (
    <div className={`block border rounded-lg p-6 hover:border-primary/50 transition-colors ${
      isPast ? 'bg-muted/30' : ''
    }`}>
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
            {isPast && (
              <span className="text-xs font-medium px-2 py-1 rounded-full bg-gray-100 text-gray-600">
                Past
              </span>
            )}
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
                ✨ AI Summary
              </span>
            )}
          </div>
          <h2 className={`text-xl font-semibold mb-2 ${isPast ? 'text-muted-foreground' : ''}`}>
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

// Summary card component for annual/quarterly/monthly/weekly summaries - expandable inline
function SummaryCard({ 
  summary, 
  type 
}: { 
  summary: Summary; 
  type: 'annual' | 'quarterly' | 'monthly' | 'weekly';
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isPending = summary.status === 'pending' || summary.status === 'generating';
  
  // Consistent colors: purple for completed, grey for pending (like documents)
  const completedColors = { bg: 'bg-purple-50 border-purple-200', badge: 'bg-purple-100 text-purple-800', icon: 'text-purple-600' };
  const pendingColors = { bg: 'bg-gray-50 border-gray-200', badge: 'bg-gray-100 text-gray-600', icon: 'text-gray-400' };
  const labels = { annual: 'Annual', quarterly: 'Quarterly', monthly: 'Monthly', weekly: 'Weekly' };
  
  const colors = isPending ? pendingColors : completedColors;
  const label = labels[type];
  
  // Get first ~200 chars of summary for preview
  const preview = isPending 
    ? (summary.status === 'generating' ? 'Summary is being generated...' : 'Summary pending generation')
    : summary.summary_text 
      ? summary.summary_text.replace(/[#*_`]/g, '').slice(0, 200) + (summary.summary_text.length > 200 ? '...' : '')
      : 'AI summary available';
  
  // Format period for display
  const periodStart = new Date(summary.period_start);
  const periodLabel = type === 'annual' 
    ? periodStart.getFullYear().toString()
    : type === 'quarterly'
      ? `Q${Math.ceil((periodStart.getMonth() + 1) / 3)} ${periodStart.getFullYear()}`
      : type === 'monthly'
        ? periodStart.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
        : `Week of ${periodStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
  
  return (
    <div className={`border rounded-lg ${colors.bg} transition-all`}>
      <button 
        onClick={() => !isPending && setIsExpanded(!isExpanded)}
        className={`w-full p-4 text-left transition-colors ${isPending ? 'cursor-default' : 'hover:bg-white/30'}`}
        disabled={isPending}
      >
        <div className="flex items-start gap-3">
          <div className={`p-2 rounded-lg bg-white/80 ${colors.icon}`}>
            {isPending ? (
              summary.status === 'generating' ? (
                <svg className="h-5 w-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              ) : (
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              )
            ) : (
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors.badge}`}>
                {isPending ? '⏳ Pending Summary' : '✨ AI Summary'}
              </span>
              <span className="text-xs text-muted-foreground">
                {label} • {periodLabel}
              </span>
            </div>
            <h3 className="font-medium text-sm mb-1">
              {summary.title || `${label} Summary`}
            </h3>
            {!isExpanded && (
              <p className="text-xs text-muted-foreground line-clamp-2">
                {preview}
              </p>
            )}
          </div>
          {!isPending && (
            <svg 
              className={`h-4 w-4 text-muted-foreground flex-shrink-0 transition-transform ${isExpanded ? 'rotate-180' : ''}`} 
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          )}
        </div>
      </button>
      
      {isExpanded && summary.summary_text && (
        <div className="px-4 pb-4 pt-0">
          <div className="bg-white/60 rounded-lg p-4 prose prose-sm prose-slate max-w-none">
            <ReactMarkdown>{summary.summary_text}</ReactMarkdown>
          </div>
          <div className="flex items-center justify-between mt-3">
            <p className="text-xs text-muted-foreground italic">
              This summary was automatically generated from civic records.
            </p>
            {summary.model_used && (
              <span className="text-xs text-muted-foreground bg-slate-100 px-2 py-0.5 rounded">
                Model: {summary.model_used}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Week group within a month
function WeekSection({ 
  week, 
  isPast = false,
  weekNumber
}: { 
  week: WeekGroup; 
  isPast?: boolean;
  weekNumber?: number;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  
  const hasPendingSummary = week.summary && (week.summary.status === 'pending' || week.summary.status === 'generating');
  const hasCompletedSummary = week.summary && week.summary.status === 'completed';
  
  return (
    <div className="border-l-2 border-muted pl-4 ml-2">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground mb-2"
      >
        <svg 
          className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`} 
          fill="none" 
          stroke="currentColor" 
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span>{weekNumber ? `Week ${weekNumber}` : 'Week'}: {week.label}</span>
        <span className="text-xs bg-muted px-2 py-0.5 rounded-full">
          {week.events.length} event{week.events.length !== 1 ? 's' : ''}
        </span>
        {hasCompletedSummary && (
          <span className="text-xs bg-purple-100 text-purple-800 px-2 py-0.5 rounded-full">
            ✨ AI Summary
          </span>
        )}
        {hasPendingSummary && (
          <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
            ⏳ Pending Summary
          </span>
        )}
      </button>
      
      {isExpanded && (
        <div className="space-y-3">
          {week.summary && (
            <SummaryCard summary={week.summary} type="weekly" />
          )}
          {week.events.map((event) => (
            <EventCard key={event.id} event={event} isPast={isPast} />
          ))}
        </div>
      )}
    </div>
  );
}

// Month group within a quarter
function MonthSection({ 
  month, 
  isExpanded,
  onToggle,
  isPast = false
}: { 
  month: MonthGroup; 
  isExpanded: boolean;
  onToggle: () => void;
  isPast?: boolean;
}) {
  const hasPendingSummary = month.summary && (month.summary.status === 'pending' || month.summary.status === 'generating');
  const hasCompletedSummary = month.summary && month.summary.status === 'completed';
  
  return (
    <div className="border-l-2 border-muted pl-4 ml-2">
      <button
        onClick={onToggle}
        className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground mb-2"
      >
        <svg 
          className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`} 
          fill="none" 
          stroke="currentColor" 
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span>{month.monthName}</span>
        <span className="text-xs bg-muted px-2 py-0.5 rounded-full">
          {month.events.length} event{month.events.length !== 1 ? 's' : ''}
        </span>
        {hasCompletedSummary && (
          <span className="text-xs bg-purple-100 text-purple-800 px-2 py-0.5 rounded-full">
            ✨ AI Summary
          </span>
        )}
        {hasPendingSummary && (
          <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
            ⏳ Pending Summary
          </span>
        )}
      </button>
      
      {isExpanded && (
        <div className="space-y-4 ml-2">
          {month.summary && (
            <SummaryCard summary={month.summary} type="monthly" />
          )}
          {month.weeks.length > 0 && (
            <div className="space-y-4">
              {month.weeks.map((week, index) => (
                <WeekSection 
                  key={week.key} 
                  week={week} 
                  isPast={isPast} 
                  weekNumber={month.weeks.length - index}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Quarter group within a year
function QuarterSection({ 
  quarter, 
  isExpanded,
  onToggle,
  expandedMonths,
  toggleMonth,
  isPast = false
}: { 
  quarter: QuarterGroup; 
  isExpanded: boolean;
  onToggle: () => void;
  expandedMonths: Set<string>;
  toggleMonth: (key: string) => void;
  isPast?: boolean;
}) {
  const hasPendingSummary = quarter.summary && (quarter.summary.status === 'pending' || quarter.summary.status === 'generating');
  const hasCompletedSummary = quarter.summary && quarter.summary.status === 'completed';
  
  return (
    <div className="border-l-2 border-muted pl-4 ml-2">
      <button
        onClick={onToggle}
        className="flex items-center gap-2 font-medium text-muted-foreground hover:text-foreground mb-2"
      >
        <svg 
          className={`h-4 w-4 transition-transform ${isExpanded ? 'rotate-90' : ''}`} 
          fill="none" 
          stroke="currentColor" 
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span>Q{quarter.quarter}</span>
        <span className="text-xs bg-muted px-2 py-0.5 rounded-full">
          {quarter.events.length} event{quarter.events.length !== 1 ? 's' : ''}
        </span>
        {hasCompletedSummary && (
          <span className="text-xs bg-purple-100 text-purple-800 px-2 py-0.5 rounded-full">
            ✨ AI Summary
          </span>
        )}
        {hasPendingSummary && (
          <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
            ⏳ Pending Summary
          </span>
        )}
      </button>
      
      {isExpanded && (
        <div className="space-y-4 ml-2">
          {quarter.summary && (
            <SummaryCard summary={quarter.summary} type="quarterly" />
          )}
          {quarter.months.map((month) => (
            <MonthSection
              key={month.key}
              month={month}
              isExpanded={expandedMonths.has(month.key)}
              onToggle={() => toggleMonth(month.key)}
              isPast={isPast}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// Year group - top level
function YearSection({ 
  yearGroup, 
  isExpanded,
  onToggle,
  expandedQuarters,
  toggleQuarter,
  expandedMonths,
  toggleMonth,
  isPast = false
}: { 
  yearGroup: YearGroup; 
  isExpanded: boolean;
  onToggle: () => void;
  expandedQuarters: Set<string>;
  toggleQuarter: (key: string) => void;
  expandedMonths: Set<string>;
  toggleMonth: (key: string) => void;
  isPast?: boolean;
}) {
  const hasPendingSummary = yearGroup.summary && (yearGroup.summary.status === 'pending' || yearGroup.summary.status === 'generating');
  const hasCompletedSummary = yearGroup.summary && yearGroup.summary.status === 'completed';
  
  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 bg-muted/50 hover:bg-muted/70 transition-colors text-left border-b"
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
          <span className="font-bold text-xl">{yearGroup.year}</span>
          {hasCompletedSummary && (
            <span className="text-xs bg-purple-100 text-purple-800 px-2 py-0.5 rounded-full">
              ✨ AI Summary
            </span>
          )}
          {hasPendingSummary && (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
              ⏳ Pending Summary
            </span>
          )}
        </div>
        <span className="text-sm text-muted-foreground bg-background px-3 py-1 rounded-full">
          {yearGroup.events.length} event{yearGroup.events.length !== 1 ? 's' : ''}
        </span>
      </button>
      
      {isExpanded && (
        <div className="p-4 space-y-4 bg-background">
          {yearGroup.summary && (
            <SummaryCard summary={yearGroup.summary} type="annual" />
          )}
          {yearGroup.quarters.map((quarter) => (
            <QuarterSection
              key={quarter.key}
              quarter={quarter}
              isExpanded={expandedQuarters.has(quarter.key)}
              onToggle={() => toggleQuarter(quarter.key)}
              expandedMonths={expandedMonths}
              toggleMonth={toggleMonth}
              isPast={isPast}
            />
          ))}
        </div>
      )}
    </div>
  );
}

type TabType = 'upcoming' | 'past';

export default function EventsPageClient({ 
  upcomingEvents, 
  pastEvents, 
  pastTotalCount,
  availableSources,
  summaries = []
}: EventsPageClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  
  // Get initial tab from URL, default to 'upcoming' if there are upcoming events
  const urlTab = searchParams.get('view') as TabType;
  const initialTab: TabType = (urlTab && ['upcoming', 'past'].includes(urlTab)) 
    ? urlTab 
    : (upcomingEvents.length > 0 ? 'upcoming' : 'past');
  
  const [activeTab, setActiveTab] = useState<TabType>(initialTab);
  const [loadedPastEvents, setLoadedPastEvents] = useState<Event[]>(pastEvents);
  const [filters, setFilters] = useState<FilterState>({
    search: '',
    sources: [],
    hasDocuments: null,
    hasVideo: null,
    hasAISummary: null,
    dateRange: 'all',
  });
  const [expandedYears, setExpandedYears] = useState<Set<string>>(() => {
    // Expand the most recent year
    if (pastEvents.length > 0) {
      const firstKey = getYearKey(pastEvents[0].start_time);
      return new Set([firstKey]);
    }
    return new Set();
  });
  const [expandedQuarters, setExpandedQuarters] = useState<Set<string>>(() => {
    // Expand the most recent quarter
    if (pastEvents.length > 0) {
      const firstKey = getQuarterKey(pastEvents[0].start_time);
      return new Set([firstKey]);
    }
    return new Set();
  });
  const [expandedMonths, setExpandedMonths] = useState<Set<string>>(() => {
    // For past events, expand the most recent month
    if (pastEvents.length > 0) {
      const firstKey = getMonthKey(pastEvents[0].start_time);
      return new Set([firstKey]);
    }
    return new Set();
  });
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(pastEvents.length < pastTotalCount);

  // Handle tab change with URL update
  const handleTabChange = useCallback((tab: TabType) => {
    setActiveTab(tab);
    const url = new URL(window.location.href);
    url.searchParams.set('view', tab);
    router.push(url.pathname + url.search, { scroll: false });
  }, [router]);

  // Filter events based on current filters
  const filteredUpcoming = useMemo(() => {
    return upcomingEvents.filter(event => eventMatchesFilters(event, filters, true));
  }, [upcomingEvents, filters]);

  const filteredPast = useMemo(() => {
    return loadedPastEvents.filter(event => eventMatchesFilters(event, filters, false));
  }, [loadedPastEvents, filters]);

  // Use hierarchical grouping
  const yearGroups = useMemo(() => 
    groupEventsHierarchically(filteredPast, summaries), 
    [filteredPast, summaries]
  );

  const toggleYear = useCallback((key: string) => {
    setExpandedYears(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const toggleQuarter = useCallback((key: string) => {
    setExpandedQuarters(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

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
      const offset = loadedPastEvents.length;
      const response = await fetch(`/api/events/past?offset=${offset}&limit=50`);
      if (!response.ok) throw new Error('Failed to load events');
      
      const data = await response.json();
      const newEvents: Event[] = data.events;
      
      if (newEvents.length === 0) {
        setHasMore(false);
      } else {
        setLoadedPastEvents(prev => [...prev, ...newEvents]);
        setHasMore(loadedPastEvents.length + newEvents.length < data.total);
      }
    } catch (error) {
      console.error('Failed to load more events:', error);
    } finally {
      setLoading(false);
    }
  }, [loadedPastEvents.length, loading, hasMore]);

  const expandAll = useCallback(() => {
    // Expand all years, quarters, and months
    const allYears = new Set(yearGroups.map(y => y.key));
    const allQuarters = new Set(yearGroups.flatMap(y => y.quarters.map(q => q.key)));
    const allMonths = new Set(yearGroups.flatMap(y => y.quarters.flatMap(q => q.months.map(m => m.key))));
    setExpandedYears(allYears);
    setExpandedQuarters(allQuarters);
    setExpandedMonths(allMonths);
  }, [yearGroups]);

  const collapseAll = useCallback(() => {
    setExpandedYears(new Set());
    setExpandedQuarters(new Set());
    setExpandedMonths(new Set());
  }, []);

  // Determine which count to show in filters
  const currentTotal = activeTab === 'upcoming' 
    ? upcomingEvents.length 
    : loadedPastEvents.length;
  const currentFiltered = activeTab === 'upcoming' 
    ? filteredUpcoming.length 
    : filteredPast.length;

  return (
    <div className="space-y-6">
      {/* Tab Navigation */}
      <div className="flex items-center gap-1 border-b">
        <button
          onClick={() => handleTabChange('upcoming')}
          className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'upcoming'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
          }`}
        >
          Upcoming
          <span className={`ml-2 px-2 py-0.5 text-xs rounded-full ${
            activeTab === 'upcoming' 
              ? 'bg-primary/10 text-primary' 
              : 'bg-muted text-muted-foreground'
          }`}>
            {upcomingEvents.length}
          </span>
        </button>
        <button
          onClick={() => handleTabChange('past')}
          className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'past'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
          }`}
        >
          Past Events
          <span className={`ml-2 px-2 py-0.5 text-xs rounded-full ${
            activeTab === 'past' 
              ? 'bg-primary/10 text-primary' 
              : 'bg-muted text-muted-foreground'
          }`}>
            {pastTotalCount}
          </span>
        </button>
      </div>

      {/* Shared Filters */}
      <EventFilters
        availableSources={availableSources}
        onFilterChange={setFilters}
        totalCount={currentTotal}
        filteredCount={currentFiltered}
        showDateRange={activeTab === 'past'}
      />

      {/* Tab Content */}
      {activeTab === 'upcoming' && (
        /* Upcoming Events Tab */
        <div>
          {filteredUpcoming.length === 0 ? (
            <div className="text-center py-8 border rounded-lg bg-muted/20">
              {upcomingEvents.length === 0 ? (
                <>
                  <p className="text-muted-foreground text-lg">
                    No upcoming events found.
                  </p>
                  <p className="text-sm text-muted-foreground mt-2">
                    Check back later for new events.
                  </p>
                </>
              ) : (
                <>
                  <p className="text-muted-foreground">No events match your filters.</p>
                  <button
                    onClick={() => setFilters({
                      search: '',
                      sources: [],
                      hasDocuments: null,
                      hasVideo: null,
                      hasAISummary: null,
                      dateRange: 'all',
                    })}
                    className="text-sm text-primary hover:underline mt-2"
                  >
                    Clear all filters
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="grid gap-4">
              {filteredUpcoming.map((event) => (
                <EventCard key={event.id} event={event} isPast={false} />
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'past' && (
        /* Past Events Tab */
        <div>
          {/* Expand/Collapse Controls */}
          {filteredPast.length > 0 && (
            <div className="flex justify-end gap-2 mb-4">
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
          )}

          {filteredPast.length === 0 ? (
            <div className="text-center py-8 border rounded-lg bg-muted/20">
              <p className="text-muted-foreground">No events match your filters.</p>
              <button
                onClick={() => setFilters({
                  search: '',
                  sources: [],
                  hasDocuments: null,
                  hasVideo: null,
                  hasAISummary: null,
                  dateRange: 'all',
                })}
                className="text-sm text-primary hover:underline mt-2"
              >
                Clear all filters
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Hierarchical Year → Quarter → Month → Week structure */}
              {yearGroups.map((yearGroup) => (
                <YearSection
                  key={yearGroup.key}
                  yearGroup={yearGroup}
                  isExpanded={expandedYears.has(yearGroup.key)}
                  onToggle={() => toggleYear(yearGroup.key)}
                  expandedQuarters={expandedQuarters}
                  toggleQuarter={toggleQuarter}
                  expandedMonths={expandedMonths}
                  toggleMonth={toggleMonth}
                  isPast={true}
                />
              ))}
            </div>
          )}

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
                  `Load More Events (${pastTotalCount - loadedPastEvents.length} remaining)`
                )}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
