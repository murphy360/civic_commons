import { sql } from '@/lib/db';
import { Suspense } from 'react';
import EventsPageClient from './EventsPageClient';
import { Header } from '../components/Header';

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
  legislation_count: number;
  ordinance_count: number;
  resolution_count: number;
  // Entity information
  entity_key: string | null;
  entity_display_name: string | null;
  entity_short_name: string | null;
  entity_domain: string | null;
  entity_icon: string | null;
  // City information
  city_id: string | null;
  city_display_name: string | null;
  city_count: number;
}

interface Summary {
  id: number;
  title: string | null;
  summary_type: string;
  period_start: Date;
  period_end: Date;
  summary_text: string | null;
  status: string;
  model_used: string | null;
}

interface PastEventsData {
  events: Event[];
  total: number;
  availableSources: string[];
  summaries: Summary[];
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
        (e.ai_summary IS NOT NULL) as has_ai_summary,
        (SELECT COUNT(DISTINCT lm.id) FROM legislation_mentions lm WHERE lm.event_id = e.id)::int as legislation_count,
        (SELECT COUNT(DISTINCT d.id) FROM legislation_mentions lm JOIN documents d ON lm.document_id = d.id WHERE lm.event_id = e.id AND d.document_type = 'ordinance')::int as ordinance_count,
        (SELECT COUNT(DISTINCT d.id) FROM legislation_mentions lm JOIN documents d ON lm.document_id = d.id WHERE lm.event_id = e.id AND d.document_type = 'resolution')::int as resolution_count,
        COALESCE(ent.entity_key, src_ent.entity_key) as entity_key,
        COALESCE(ent.display_name, src_ent.display_name) as entity_display_name,
        COALESCE(ent.short_name, src_ent.short_name) as entity_short_name,
        COALESCE(ent.domain, src_ent.domain) as entity_domain,
        COALESCE(ent.icon, src_ent.icon) as entity_icon,
        (SELECT ec.city_id FROM event_cities ec WHERE ec.event_id = e.id AND ec.is_primary = true LIMIT 1) as city_id,
        (SELECT c.display_name FROM event_cities ec JOIN cities c ON ec.city_id = c.city_id WHERE ec.event_id = e.id AND ec.is_primary = true LIMIT 1) as city_display_name,
        (SELECT COUNT(*) FROM event_cities ec WHERE ec.event_id = e.id)::int as city_count
      FROM events e
      LEFT JOIN event_sources es ON e.id = es.event_id
      LEFT JOIN sources s ON es.source_id = s.id
      LEFT JOIN entities ent ON e.entity_id = ent.id
      LEFT JOIN entities src_ent ON s.entity_id = src_ent.id
      WHERE e.start_time >= NOW() - INTERVAL '1 day'
      GROUP BY e.id, ent.entity_key, ent.display_name, ent.short_name, ent.domain, ent.icon,
               src_ent.entity_key, src_ent.display_name, src_ent.short_name, src_ent.domain, src_ent.icon
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

    // Get distinct sources for filtering
    const sourcesResult = await sql<{ name: string }[]>`
      SELECT DISTINCT s.name
      FROM sources s
      JOIN event_sources es ON s.id = es.source_id
      JOIN events e ON es.event_id = e.id
      WHERE s.name IS NOT NULL
      ORDER BY s.name
    `;
    const availableSources = sourcesResult.map(r => r.name);

    // Get annual, quarterly, monthly and weekly summaries (including pending)
    const summaries = await sql<Summary[]>`
      SELECT 
        id, title, summary_type, period_start, period_end, summary_text, status, model_used
      FROM summaries
      WHERE summary_type IN ('annual', 'quarterly', 'monthly', 'weekly')
        AND status IN ('completed', 'pending', 'generating')
        AND period_start >= NOW() - INTERVAL '2 years'
      ORDER BY period_start DESC
    `;

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
        (e.ai_summary IS NOT NULL) as has_ai_summary,
        (SELECT COUNT(DISTINCT lm.id) FROM legislation_mentions lm WHERE lm.event_id = e.id)::int as legislation_count,
        (SELECT COUNT(DISTINCT d.id) FROM legislation_mentions lm JOIN documents d ON lm.document_id = d.id WHERE lm.event_id = e.id AND d.document_type = 'ordinance')::int as ordinance_count,
        (SELECT COUNT(DISTINCT d.id) FROM legislation_mentions lm JOIN documents d ON lm.document_id = d.id WHERE lm.event_id = e.id AND d.document_type = 'resolution')::int as resolution_count,
        COALESCE(ent.entity_key, src_ent.entity_key) as entity_key,
        COALESCE(ent.display_name, src_ent.display_name) as entity_display_name,
        COALESCE(ent.short_name, src_ent.short_name) as entity_short_name,
        COALESCE(ent.domain, src_ent.domain) as entity_domain,
        COALESCE(ent.icon, src_ent.icon) as entity_icon,
        (SELECT ec.city_id FROM event_cities ec WHERE ec.event_id = e.id AND ec.is_primary = true LIMIT 1) as city_id,
        (SELECT c.display_name FROM event_cities ec JOIN cities c ON ec.city_id = c.city_id WHERE ec.event_id = e.id AND ec.is_primary = true LIMIT 1) as city_display_name,
        (SELECT COUNT(*) FROM event_cities ec WHERE ec.event_id = e.id)::int as city_count
      FROM events e
      LEFT JOIN event_sources es ON e.id = es.event_id
      LEFT JOIN sources s ON es.source_id = s.id
      LEFT JOIN entities ent ON e.entity_id = ent.id
      LEFT JOIN entities src_ent ON s.entity_id = src_ent.id
      WHERE e.start_time < NOW() - INTERVAL '1 day'
      GROUP BY e.id, ent.entity_key, ent.display_name, ent.short_name, ent.domain, ent.icon,
               src_ent.entity_key, src_ent.display_name, src_ent.short_name, src_ent.domain, src_ent.icon
      ORDER BY e.start_time DESC
      LIMIT 50
    `;
    return { events, total, availableSources, summaries };
  } catch (error) {
    console.error('Failed to fetch past events:', error);
    return { events: [], total: 0, availableSources: [], summaries: [] };
  }
}

export default async function EventsPage() {
  const [upcomingEvents, pastEventsData] = await Promise.all([
    getUpcomingEvents(),
    getPastEvents(),
  ]);

  // Serialize dates for the client component (handle both Date objects and strings)
  const serializedUpcoming = upcomingEvents.map(event => ({
    ...event,
    start_time: typeof event.start_time === 'string' 
      ? event.start_time 
      : event.start_time.toISOString(),
    end_time: event.end_time 
      ? (typeof event.end_time === 'string' ? event.end_time : event.end_time.toISOString())
      : null,
  }));

  const serializedPastEvents = pastEventsData.events.map(event => ({
    ...event,
    start_time: typeof event.start_time === 'string' 
      ? event.start_time 
      : event.start_time.toISOString(),
    end_time: event.end_time 
      ? (typeof event.end_time === 'string' ? event.end_time : event.end_time.toISOString())
      : null,
  }));

  const serializedSummaries = pastEventsData.summaries.map(summary => ({
    ...summary,
    period_start: typeof summary.period_start === 'string'
      ? summary.period_start
      : summary.period_start.toISOString(),
    period_end: typeof summary.period_end === 'string'
      ? summary.period_end
      : summary.period_end.toISOString(),
  }));

  return (
    <div className="flex flex-col min-h-screen">
      <Header />

      {/* Main Content */}
      <main className="container py-8">
        <h1 className="text-3xl font-bold mb-8">Events</h1>
        
        <Suspense fallback={<div className="text-center py-8">Loading events...</div>}>
          <EventsPageClient
            upcomingEvents={serializedUpcoming}
            pastEvents={serializedPastEvents}
            pastTotalCount={pastEventsData.total}
            availableSources={pastEventsData.availableSources}
            summaries={serializedSummaries}
          />
        </Suspense>
      </main>
    </div>
  );
}
