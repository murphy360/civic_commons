import Link from 'next/link';
import { notFound } from 'next/navigation';
import { sql } from '@/lib/db';
import { AISummarySection } from './AISummarySection';
import { ReanalyzeEventButton } from './ReanalyzeEventButton';
import { Header } from '../../components/Header';
import { EntityFlair, type EntityInfo } from '../../components/EntityFlair';

export const dynamic = 'force-dynamic';

interface Event {
  id: number;
  title: string;
  description: string | null;
  start_time: Date;
  end_time: Date | null;
  location: string | null;
  category: string | null;
  source_url: string | null;
  video_url: string | null;
  source_names: string;
  source_count: number;
  ai_summary: string | null;
  ai_summary_updated_at: Date | null;
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

interface EventDocument {
  id: number;
  title: string;
  document_type: string | null;
  relationship: string;
  source_url: string | null;
  content_text: string | null;
  ai_summary: string | null;
  published_date: Date | null;
}

interface EventLegislation {
  id: number;
  legislation_number: string;
  legislation_type: string;
  legislation_title: string | null;
  document_title: string;
  action_taken: string;
  vote_result: string | null;
  excerpt: string | null;
  mentioned_date: Date | null;
  document_id: number;
  ordinance_id: number | null;
}

async function getEvent(id: number): Promise<Event | null> {
  try {
    const events = await sql<Event[]>`
      SELECT 
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.location,
        e.category,
        (SELECT es2.source_url FROM event_sources es2 WHERE es2.event_id = e.id ORDER BY es2.first_seen_at LIMIT 1) as source_url,
        e.video_url,
        e.ai_summary,
        e.ai_summary_updated_at,
        COALESCE(string_agg(DISTINCT s.name, ', ' ORDER BY s.name), 'Unknown') as source_names,
        COUNT(DISTINCT es.source_id)::int as source_count,
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
      WHERE e.id = ${id}
      GROUP BY e.id, ent.entity_key, ent.display_name, ent.short_name, ent.domain, ent.icon,
               src_ent.entity_key, src_ent.display_name, src_ent.short_name, src_ent.domain, src_ent.icon
    `;
    return events[0] || null;
  } catch (error) {
    console.error('Failed to fetch event:', error);
    return null;
  }
}

async function getEventDocuments(eventId: number): Promise<EventDocument[]> {
  try {
    const documents = await sql<EventDocument[]>`
      SELECT 
        d.id,
        d.title,
        d.document_type,
        ed.relationship,
        d.source_url,
        d.content_text,
        d.ai_summary,
        d.published_date
      FROM event_documents ed
      JOIN documents d ON ed.document_id = d.id
      WHERE ed.event_id = ${eventId}
      ORDER BY 
        CASE ed.relationship 
          WHEN 'agenda' THEN 1 
          WHEN 'minutes' THEN 2 
          WHEN 'packet' THEN 3
          ELSE 4 
        END
    `;
    return documents;
  } catch (error) {
    console.error('Failed to fetch event documents:', error);
    return [];
  }
}

async function getEventLegislation(eventId: number): Promise<EventLegislation[]> {
  try {
    const legislation = await sql<EventLegislation[]>`
      SELECT 
        lm.id,
        COALESCE(lm.legislation_number, '') as legislation_number,
        lm.legislation_type,
        lm.legislation_title,
        d.title as document_title,
        lm.action_taken,
        lm.vote_result,
        lm.excerpt,
        lm.mentioned_date,
        d.id as document_id,
        (SELECT id FROM documents 
         WHERE document_type IN ('ordinance', 'resolution')
         AND legislation_number = lm.legislation_number
         ORDER BY document_type DESC, published_date DESC
         LIMIT 1) as ordinance_id
      FROM legislation_mentions lm
      JOIN documents d ON lm.document_id = d.id
      WHERE lm.event_id = ${eventId}
      ORDER BY 
        CASE lm.legislation_type 
          WHEN 'ordinance' THEN 1 
          WHEN 'resolution' THEN 2
          ELSE 3 
        END,
        lm.legislation_number DESC NULLS LAST
    `;
    return legislation;
  } catch (error) {
    console.error('Failed to fetch event legislation:', error);
    return [];
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

function formatShortDate(date: Date | null): string {
  if (!date) return '';
  return new Date(date).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function formatDateDiff(eventDate: Date, publishedDate: Date | null): string | null {
  if (!publishedDate) return null;
  
  const eventTime = new Date(eventDate).getTime();
  const publishTime = new Date(publishedDate).getTime();
  const diffDays = Math.round((publishTime - eventTime) / (1000 * 60 * 60 * 24));
  
  if (diffDays === 0) return 'same day';
  if (diffDays > 0) {
    return `${diffDays} day${diffDays !== 1 ? 's' : ''} after`;
  } else {
    const absDays = Math.abs(diffDays);
    return `${absDays} day${absDays !== 1 ? 's' : ''} before`;
  }
}

function formatTime(date: Date): string {
  return new Date(date).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function getDocumentLabel(docType: string | null, relationship: string): string {
  // Prefer document_type over relationship for more accurate labeling
  const labels: Record<string, string> = {
    agenda: 'Agenda',
    minutes: 'Minutes',
    packet: 'Meeting Packet',
    video: 'Video',
    transcript: 'Transcript',
    ordinance: 'Ordinance',
    resolution: 'Resolution',
    attachment: 'Attachment',
    related: 'Related Document',
  };
  
  // Use document_type if it provides a meaningful label
  if (docType && labels[docType]) {
    return labels[docType];
  }
  // Fall back to relationship
  return labels[relationship] || relationship;
}

function getDocumentLabelColor(docType: string | null, relationship: string): string {
  // Prefer document_type over relationship for color coding
  const colors: Record<string, string> = {
    agenda: 'bg-green-100 text-green-800',
    minutes: 'bg-blue-100 text-blue-800',
    packet: 'bg-purple-100 text-purple-800',
    video: 'bg-red-100 text-red-800',
    transcript: 'bg-yellow-100 text-yellow-800',
    ordinance: 'bg-orange-100 text-orange-800',
    resolution: 'bg-amber-100 text-amber-800',
    attachment: 'bg-gray-100 text-gray-800',
    related: 'bg-gray-100 text-gray-800',
  };
  
  // Use document_type if it provides a meaningful color
  if (docType && colors[docType]) {
    return colors[docType];
  }
  // Fall back to relationship
  return colors[relationship] || 'bg-gray-100 text-gray-800';
}

export default async function EventDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const eventId = parseInt(params.id);
  
  if (isNaN(eventId)) {
    notFound();
  }

  const event = await getEvent(eventId);
  
  if (!event) {
    notFound();
  }

  const [documents, legislation] = await Promise.all([
    getEventDocuments(eventId),
    getEventLegislation(eventId),
  ]);

  return (
    <div className="flex flex-col min-h-screen">
      <Header />

      {/* Main Content */}
      <main className="container py-8">
        {/* Back link */}
        <Link 
          href="/events" 
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-6"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to Events
        </Link>

        {/* Event Header */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            {/* City badge */}
            {event.city_display_name && (
              <span 
                className="text-sm font-medium px-3 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200"
                title={event.city_count > 1 ? `Also in ${event.city_count - 1} other ${event.city_count === 2 ? 'city' : 'cities'}` : undefined}
              >
                📍 {event.city_display_name}{event.city_count > 1 ? ` +${event.city_count - 1}` : ''}
              </span>
            )}
            {/* Entity badge */}
            {event.entity_display_name && (
              <EntityFlair 
                entity={{
                  entity_key: event.entity_key || undefined,
                  entity_display_name: event.entity_display_name || undefined,
                  entity_short_name: event.entity_short_name || undefined,
                  entity_domain: event.entity_domain || undefined,
                  entity_icon: event.entity_icon || undefined,
                }} 
                size="md" 
                showIcon={true} 
              />
            )}
            {/* Fall back to source names if no entity */}
            {!event.entity_display_name && event.source_names.split(', ').map((source, idx) => (
              <span 
                key={idx}
                className="text-sm font-medium px-3 py-1 rounded-full bg-primary/10 text-primary"
              >
                {source}
              </span>
            ))}
            {event.source_count > 1 && (
              <span className="text-sm font-medium px-3 py-1 rounded-full bg-emerald-100 text-emerald-800" title="Verified across multiple sources">
                ✓ Verified ({event.source_count} sources)
              </span>
            )}
          </div>
          <h1 className="text-3xl font-bold mb-4">{event.title}</h1>
          
          <div className="flex flex-col gap-2 text-muted-foreground">
            <div className="flex items-center gap-2">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span className="text-lg">{formatDate(event.start_time)}</span>
            </div>
            <div className="flex items-center gap-2">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-lg">
                {formatTime(event.start_time)}
                {event.end_time && ` - ${formatTime(event.end_time)}`}
              </span>
            </div>
            {event.location && (
              <div className="flex items-center gap-2">
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <span className="text-lg">{event.location}</span>
              </div>
            )}
          </div>

          {event.description && (
            <p className="mt-6 text-lg">{event.description}</p>
          )}

          {/* Admin Tools */}
          <div className="mt-6 p-4 bg-slate-50 border rounded-lg">
            <h3 className="text-sm font-medium text-gray-700 mb-3">Admin Tools</h3>
            <ReanalyzeEventButton eventId={event.id} />
          </div>

          {/* AI Summary Section */}
          <AISummarySection 
            eventId={event.id}
            summary={event.ai_summary}
            updatedAt={event.ai_summary_updated_at}
            hasDocuments={documents.length > 0}
          />

          <div className="flex flex-wrap gap-3 mt-6">
            {event.video_url && (
              <a
                href={event.video_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-red-600 text-white hover:bg-red-700 transition-colors"
              >
                <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
                </svg>
                Watch Recording
              </a>
            )}
            {event.source_url && (
              <a
                href={event.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md border hover:bg-accent transition-colors"
              >
                View Official Source
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
            )}
          </div>
        </div>

        {/* Documents & Legislation Section */}
        {(documents.length > 0 || legislation.length > 0) && (
          <div className="mt-8">
            <h2 className="text-2xl font-bold mb-4">Documents & Legislation</h2>
            <div className="grid gap-4">
              {/* Documents */}
              {documents.map((doc) => {
                const dateDiff = formatDateDiff(event.start_time, doc.published_date);
                return (
                <div
                  key={`doc-${doc.id}`}
                  className="border rounded-lg p-6"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        <span className={`text-xs font-medium px-2 py-1 rounded-full ${getDocumentLabelColor(doc.document_type, doc.relationship)}`}>
                          {getDocumentLabel(doc.document_type, doc.relationship)}
                        </span>
                        {doc.published_date && (
                          <span className="text-xs text-muted-foreground">
                            {formatShortDate(doc.published_date)}
                            {dateDiff && (
                              <span className={`ml-1 ${
                                dateDiff.includes('before') ? 'text-green-600' : 
                                dateDiff.includes('after') ? 'text-blue-600' : 
                                'text-gray-600'
                              }`}>
                                ({dateDiff})
                              </span>
                            )}
                          </span>
                        )}
                        {doc.ai_summary && (
                          <span className="text-xs font-medium px-2 py-1 rounded-full bg-indigo-100 text-indigo-800">
                            ✨ AI Summary
                          </span>
                        )}
                      </div>
                      <h3 className="text-lg font-semibold mb-2">{doc.title}</h3>
                      {doc.ai_summary ? (
                        <div className="bg-indigo-50 border border-indigo-100 rounded-md p-3 mb-2">
                          <p className="text-sm text-indigo-900">
                            {doc.ai_summary}
                          </p>
                        </div>
                      ) : doc.content_text && (
                        <p className="text-muted-foreground text-sm line-clamp-3">
                          {doc.content_text}
                        </p>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <Link
                        href={`/documents/${doc.id}`}
                        className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                      >
                        Read
                      </Link>
                      {doc.source_url && (
                        <a
                          href={doc.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md border hover:bg-accent transition-colors"
                        >
                          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                          </svg>
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              )})}

              {/* Legislation */}
              {legislation.map((leg) => (
                <div
                  key={`leg-${leg.id}`}
                  className="border border-orange-200 rounded-lg p-6 bg-orange-50"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        <span className={`text-xs font-medium px-2 py-1 rounded-full ${
                          leg.legislation_type === 'ordinance' 
                            ? 'bg-orange-100 text-orange-800' 
                            : 'bg-amber-100 text-amber-800'
                        }`}>
                          {leg.legislation_type === 'ordinance' ? '📜 Ordinance' : '📋 Resolution'}
                          {leg.legislation_number && ` - ${leg.legislation_number}`}
                        </span>
                        {leg.action_taken && (
                          <span className="text-xs font-medium px-2 py-1 rounded-full bg-slate-100 text-slate-700">
                            {leg.action_taken.charAt(0).toUpperCase() + leg.action_taken.slice(1)}
                          </span>
                        )}
                        {leg.vote_result && (
                          <span className="text-xs font-medium px-2 py-1 rounded-full bg-green-100 text-green-800">
                            ✓ {leg.vote_result}
                          </span>
                        )}
                      </div>
                      <h3 className="text-lg font-semibold mb-2">
                        {leg.legislation_title || leg.document_title}
                      </h3>
                      {leg.excerpt && (
                        <p className="text-sm text-slate-700 italic mb-2 line-clamp-3">
                          "{leg.excerpt}"
                        </p>
                      )}
                      <p className="text-xs text-muted-foreground">
                        {leg.ordinance_id ? (
                          <>Mentioned in: <Link href={`/documents/${leg.document_id}`} className="font-medium text-primary hover:underline">{leg.document_title}</Link></>
                        ) : (
                          <>Discussed in: <Link href={`/documents/${leg.document_id}`} className="font-medium text-primary hover:underline">{leg.document_title}</Link></>
                        )}
                      </p>
                    </div>
                    <Link
                      href={`/documents/${leg.ordinance_id || leg.document_id}`}
                      className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md bg-orange-100 text-orange-800 hover:bg-orange-200 transition-colors flex-shrink-0"
                    >
                      {leg.ordinance_id ? 'View Ordinance' : 'View Details'}
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {documents.length === 0 && legislation.length === 0 && (
          <div className="mt-8 p-8 border rounded-lg text-center">
            <p className="text-muted-foreground">
              No documents or legislation have been associated with this event yet.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
