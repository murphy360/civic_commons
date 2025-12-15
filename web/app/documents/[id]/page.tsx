import Link from 'next/link';
import { sql } from '@/lib/db';
import { notFound } from 'next/navigation';

export const dynamic = 'force-dynamic';

interface Document {
  id: number;
  title: string;
  document_type: string | null;
  content_text: string | null;
  content_markdown: string | null;
  source_url: string | null;
  file_url: string | null;
  local_path: string | null;
  file_size_bytes: number | null;
  mime_type: string | null;
  published_date: Date | null;
  created_at: Date;
  source_name: string;
}

interface RelatedEvent {
  id: number;
  title: string;
  start_time: Date;
  relationship: string;
}

async function getDocument(id: number): Promise<Document | null> {
  try {
    const documents = await sql<Document[]>`
      SELECT 
        d.id,
        d.title,
        d.document_type,
        d.content_text,
        d.content_markdown,
        d.source_url,
        d.file_url,
        d.local_path,
        d.file_size_bytes,
        d.mime_type,
        d.published_date,
        d.created_at,
        s.name as source_name
      FROM documents d
      JOIN sources s ON d.source_id = s.id
      WHERE d.id = ${id}
      LIMIT 1
    `;
    return documents[0] || null;
  } catch (error) {
    console.error('Failed to fetch document:', error);
    return null;
  }
}

async function getRelatedEvents(documentId: number): Promise<RelatedEvent[]> {
  try {
    const events = await sql<RelatedEvent[]>`
      SELECT 
        e.id,
        e.title,
        e.start_time,
        ed.relationship
      FROM events e
      JOIN event_documents ed ON e.id = ed.event_id
      WHERE ed.document_id = ${documentId}
      ORDER BY e.start_time DESC
    `;
    return events;
  } catch (error) {
    console.error('Failed to fetch related events:', error);
    return [];
  }
}

function formatDate(date: Date | null): string {
  if (!date) return 'Unknown date';
  return new Date(date).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function getDocumentTypeLabel(type: string | null): string {
  const labels: Record<string, string> = {
    minutes: 'Meeting Minutes',
    agenda: 'Agenda',
    resolution: 'Resolution',
    ordinance: 'Ordinance',
    report: 'Report',
    notice: 'Public Notice',
    attachment: 'Attachment',
    packet: 'Meeting Packet',
    video: 'Video Recording',
  };
  return labels[type || ''] || type || 'Document';
}

function getDocumentTypeBadgeColor(type: string | null): string {
  const colors: Record<string, string> = {
    minutes: 'bg-blue-100 text-blue-800',
    agenda: 'bg-green-100 text-green-800',
    resolution: 'bg-purple-100 text-purple-800',
    ordinance: 'bg-orange-100 text-orange-800',
    report: 'bg-gray-100 text-gray-800',
    notice: 'bg-yellow-100 text-yellow-800',
    attachment: 'bg-slate-100 text-slate-800',
    packet: 'bg-indigo-100 text-indigo-800',
    video: 'bg-red-100 text-red-800',
  };
  return colors[type || ''] || 'bg-gray-100 text-gray-800';
}

function getRelationshipLabel(relationship: string | null): string {
  const labels: Record<string, string> = {
    agenda: 'Agenda for',
    minutes: 'Minutes of',
    attachment: 'Attached to',
    packet: 'Packet for',
    video: 'Recording of',
  };
  return labels[relationship || ''] || 'Related to';
}

/**
 * Format file size in human-readable format
 */
function formatFileSize(bytes: number | null): string {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
}

/**
 * Get the best download URL for a document
 * Prefers local files, falls back to source URL
 */
function getDownloadUrl(document: Document): string | null {
  if (document.local_path) {
    // Local path is stored as relative path like "2025/01/filename.pdf"
    return `/api/files/${document.local_path}`;
  }
  return document.file_url || document.source_url;
}

export default async function DocumentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const documentId = parseInt(id, 10);
  
  if (isNaN(documentId)) {
    notFound();
  }

  const document = await getDocument(documentId);
  
  if (!document) {
    notFound();
  }

  const relatedEvents = await getRelatedEvents(documentId);

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
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Events
            </Link>
            <Link
              href="/documents"
              className="transition-colors hover:text-foreground/80 text-foreground"
            >
              Documents
            </Link>
          </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 container py-8">
        {/* Back link */}
        <Link 
          href="/documents"
          className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground mb-6"
        >
          <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back to Documents
        </Link>

        {/* Document Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-4">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getDocumentTypeBadgeColor(document.document_type)}`}>
              {getDocumentTypeLabel(document.document_type)}
            </span>
            <span className="text-sm text-muted-foreground">
              {document.source_name}
            </span>
          </div>
          
          <h1 className="text-3xl font-bold mb-4">{document.title}</h1>
          
          <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
            {document.published_date && (
              <div className="flex items-center gap-1">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                <span>Published {formatDate(document.published_date)}</span>
              </div>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap gap-3 mb-8">
          {/* Download button - prefers local file */}
          {(() => {
            const downloadUrl = getDownloadUrl(document);
            const isLocal = !!document.local_path;
            if (!downloadUrl) return null;
            
            return (
              <a
                href={downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Download File
                {document.file_size_bytes && (
                  <span className="text-xs opacity-80">
                    ({formatFileSize(document.file_size_bytes)})
                  </span>
                )}
              </a>
            );
          })()}
          
          {/* View original source link */}
          {document.source_url && (
            <a
              href={document.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md border hover:bg-accent transition-colors"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              View Original Source
            </a>
          )}
        </div>

        {/* Related Events */}
        {relatedEvents.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl font-semibold mb-4">Related Events</h2>
            <div className="space-y-3">
              {relatedEvents.map((event) => (
                <Link
                  key={event.id}
                  href={`/events/${event.id}`}
                  className="block p-4 border rounded-lg hover:bg-accent/50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-sm text-muted-foreground">
                        {getRelationshipLabel(event.relationship)}
                      </span>
                      <h3 className="font-medium">{event.title}</h3>
                    </div>
                    <span className="text-sm text-muted-foreground">
                      {formatDate(event.start_time)}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* PDF Viewer - Show embedded PDF if we have a local file */}
        {document.local_path && document.mime_type === 'application/pdf' && (
          <div className="mb-8">
            <h2 className="text-xl font-semibold mb-4">Document Preview</h2>
            <div className="border rounded-lg overflow-hidden bg-gray-100">
              <iframe
                src={`/api/files/${document.local_path}`}
                className="w-full h-[800px]"
                title={document.title}
              />
            </div>
          </div>
        )}

        {/* Fallback PDF viewer using source URL if no local file */}
        {!document.local_path && document.source_url && (
          <div className="mb-8">
            <h2 className="text-xl font-semibold mb-4">Document Preview</h2>
            <div className="border rounded-lg overflow-hidden bg-gray-100">
              <iframe
                src={document.source_url}
                className="w-full h-[800px]"
                title={document.title}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-2">
              Embedded from original source. If the preview doesn&apos;t load, use the &quot;View Original Source&quot; button above.
            </p>
          </div>
        )}

        {/* Document Content - Show extracted text if available */}
        {(document.content_markdown || document.content_text) && (
          <div className="mb-8">
            <h2 className="text-xl font-semibold mb-4">Extracted Content</h2>
            <div className="p-6 border rounded-lg bg-muted/30">
              {document.content_markdown ? (
                <div 
                  className="prose prose-sm max-w-none dark:prose-invert"
                  dangerouslySetInnerHTML={{ __html: document.content_markdown }}
                />
              ) : (
                <p className="whitespace-pre-wrap text-sm">{document.content_text}</p>
              )}
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t py-6">
        <div className="container text-center text-sm text-muted-foreground">
          <p>Civic Commons - Making local government accessible</p>
        </div>
      </footer>
    </div>
  );
}
