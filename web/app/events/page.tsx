import Link from 'next/link';
import { sql } from '@/lib/db';
import PastEventsSection from './PastEventsSection';

export const dynamic = 'force-dynamic';

interface Event {
  id: number;
  title: string;
  description: string | null;
  start_time: Date;
  end_time: Date | null;
  location: string | null;
  source_url: string | null;
  video_url: string | null;
  source_names: string;  // Comma-separated list of source names
  source_count: number;
  document_count: number;
  has_agenda: number;
  has_minutes: number;
  first_doc_id: number | null;
  has_ai_summary: boolean;
}

interface PastEventsData {
  events: Event[];
  total: number;
}

async function getUpcomingEvents(): Promise<Event[]> {
  try {
    const events = await sql<Event[]>`
      SELECT 
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.location,
        (SELECT es2.source_url FROM event_sources es2 WHERE es2.event_id = e.id ORDER BY es2.first_seen_at LIMIT 1) as source_url,
        e.video_url,
        COALESCE(string_agg(DISTINCT s.name, ', ' ORDER BY s.name), 'Unknown') as source_names,
        COUNT(DISTINCT es.source_id)::int as source_count,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id)::int as document_count,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'agenda')::int as has_agenda,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'minutes')::int as has_minutes,
        (SELECT ed.document_id FROM event_documents ed WHERE ed.event_id = e.id ORDER BY 
          CASE ed.relationship WHEN 'agenda' THEN 1 WHEN 'minutes' THEN 2 ELSE 3 END LIMIT 1)::int as first_doc_id,
        (e.ai_summary IS NOT NULL) as has_ai_summary
      FROM events e
      LEFT JOIN event_sources es ON e.id = es.event_id
      LEFT JOIN sources s ON es.source_id = s.id
      WHERE e.start_time >= NOW() - INTERVAL '1 day'
      GROUP BY e.id
      ORDER BY e.start_time ASC
      LIMIT 50
    `;
    return events;
  } catch (error) {
    console.error('Failed to fetch upcoming events:', error);
    return [];
  }
}

async function getPastEvents(): Promise<PastEventsData> {
  try {
    // Get total count
    const countResult = await sql<{ count: number }[]>`
      SELECT COUNT(*)::int as count 
      FROM events 
      WHERE start_time < NOW() - INTERVAL '1 day'
    `;
    const total = countResult[0]?.count || 0;

    // Get initial batch of events
    const events = await sql<Event[]>`
      SELECT 
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.location,
        (SELECT es2.source_url FROM event_sources es2 WHERE es2.event_id = e.id ORDER BY es2.first_seen_at LIMIT 1) as source_url,
        e.video_url,
        COALESCE(string_agg(DISTINCT s.name, ', ' ORDER BY s.name), 'Unknown') as source_names,
        COUNT(DISTINCT es.source_id)::int as source_count,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id)::int as document_count,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'agenda')::int as has_agenda,
        (SELECT COUNT(*) FROM event_documents ed WHERE ed.event_id = e.id AND ed.relationship = 'minutes')::int as has_minutes,
        (SELECT ed.document_id FROM event_documents ed WHERE ed.event_id = e.id ORDER BY 
          CASE ed.relationship WHEN 'agenda' THEN 1 WHEN 'minutes' THEN 2 ELSE 3 END LIMIT 1)::int as first_doc_id,
        (e.ai_summary IS NOT NULL) as has_ai_summary
      FROM events e
      LEFT JOIN event_sources es ON e.id = es.event_id
      LEFT JOIN sources s ON es.source_id = s.id
      WHERE e.start_time < NOW() - INTERVAL '1 day'
      GROUP BY e.id
      ORDER BY e.start_time DESC
      LIMIT 50
    `;
    return { events, total };
  } catch (error) {
    console.error('Failed to fetch past events:', error);
    return { events: [], total: 0 };
  }
}

function formatDate(date: Date): string {
  return new Date(date).toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function formatTime(date: Date): string {
  return new Date(date).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function isPastEvent(date: Date): boolean {
  const eventDate = new Date(date);
  const now = new Date();
  // Consider events from today as "upcoming" still
  now.setHours(0, 0, 0, 0);
  return eventDate < now;
}

function EventCard({ event, isPast = false }: { event: Event; isPast?: boolean }) {
  // Split source names into array
  const sources = event.source_names ? event.source_names.split(', ') : [];
  
  // Determine document link - single doc goes directly to doc, multiple goes to event#documents
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
                ✨ AI Overview
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

export default async function EventsPage() {
  const [upcomingEvents, pastEventsData] = await Promise.all([
    getUpcomingEvents(),
    getPastEvents(),
  ]);

  // Serialize dates for the client component (handle both Date objects and strings)
  const serializedPastEvents = pastEventsData.events.map(event => ({
    ...event,
    start_time: typeof event.start_time === 'string' 
      ? event.start_time 
      : event.start_time.toISOString(),
    end_time: event.end_time 
      ? (typeof event.end_time === 'string' ? event.end_time : event.end_time.toISOString())
      : null,
  }));

  return (
    <div className="flex flex-col min-h-screen">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-14 items-center">
          <div className="mr-4 flex">
            <Link href="/" className="mr-6 flex items-center space-x-2">
              <span className="font-bold text-xl">Civic Commons</span>
            </Link>
          </div>
          <nav className="flex items-center space-x-6 text-sm font-medium">
            <Link
              href="/events"
              className="transition-colors hover:text-foreground/80 text-foreground"
            >
              Events
            </Link>
            <Link
              href="/documents"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Documents
            </Link>
            <Link
              href="/search"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Search
            </Link>
          </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="container py-8">
        {/* Upcoming Events Section */}
        <section className="mb-12">
          <h1 className="text-3xl font-bold mb-8">Upcoming Events</h1>
          
          {upcomingEvents.length === 0 ? (
            <div className="text-center py-8 border rounded-lg bg-muted/20">
              <p className="text-muted-foreground text-lg">
                No upcoming events found.
              </p>
              <p className="text-sm text-muted-foreground mt-2">
                Check back later for new events.
              </p>
            </div>
          ) : (
            <div className="grid gap-4">
              {upcomingEvents.map((event) => (
                <EventCard key={event.id} event={event} isPast={false} />
              ))}
            </div>
          )}
        </section>

        {/* Past Events Section - Client Component with month grouping */}
        <PastEventsSection 
          initialEvents={serializedPastEvents}
          totalCount={pastEventsData.total}
        />
      </main>
    </div>
  );
}
