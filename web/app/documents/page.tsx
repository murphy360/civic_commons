import Link from 'next/link';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

interface Document {
  id: number;
  title: string;
  document_type: string | null;
  content_text: string | null;
  source_url: string | null;
  local_path: string | null;
  file_size_bytes: number | null;
  published_date: Date | null;
  source_name: string;
  ai_summary: string | null;
  event_count: number;
}

type FilterType = 'unlinked' | 'linked' | 'all';

async function getDocuments(filter: FilterType): Promise<Document[]> {
  try {
    let documents: Document[];
    
    if (filter === 'unlinked') {
      documents = await sql<Document[]>`
        SELECT 
          d.id,
          d.title,
          d.document_type,
          d.content_text,
          d.source_url,
          d.local_path,
          d.file_size_bytes,
          d.published_date,
          s.name as source_name,
          d.ai_summary,
          0 as event_count
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        WHERE NOT EXISTS (
          SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id
        )
        ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
        LIMIT 100
      `;
    } else if (filter === 'linked') {
      documents = await sql<Document[]>`
        SELECT 
          d.id,
          d.title,
          d.document_type,
          d.content_text,
          d.source_url,
          d.local_path,
          d.file_size_bytes,
          d.published_date,
          s.name as source_name,
          d.ai_summary,
          (SELECT COUNT(*) FROM event_documents ed WHERE ed.document_id = d.id)::int as event_count
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        WHERE EXISTS (
          SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id
        )
        ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
        LIMIT 100
      `;
    } else {
      documents = await sql<Document[]>`
        SELECT 
          d.id,
          d.title,
          d.document_type,
          d.content_text,
          d.source_url,
          d.local_path,
          d.file_size_bytes,
          d.published_date,
          s.name as source_name,
          d.ai_summary,
          (SELECT COUNT(*) FROM event_documents ed WHERE ed.document_id = d.id)::int as event_count
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
        LIMIT 100
      `;
    }
    return documents;
  } catch (error) {
    console.error('Failed to fetch documents:', error);
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

function getDocumentTypeLabel(type: string | null): string {
  const labels: Record<string, string> = {
    minutes: 'Meeting Minutes',
    agenda: 'Agenda',
    resolution: 'Resolution',
    ordinance: 'Ordinance',
    report: 'Report',
    notice: 'Public Notice',
    attachment: 'Attachment',
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
  };
  return colors[type || ''] || 'bg-gray-100 text-gray-800';
}

function truncateText(text: string | null, maxLength: number = 200): string {
  if (!text) return '';
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength).trim() + '...';
}

export default async function DocumentsPage({
  searchParams,
}: {
  searchParams: Promise<{ filter?: string }>;
}) {
  const params = await searchParams;
  const filter = (params.filter as FilterType) || 'unlinked';
  const documents = await getDocuments(filter);

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
            <Link
              href="/newsletters"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Newsletters
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
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <h1 className="text-3xl font-bold">Documents</h1>
          
          {/* Filter buttons */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground mr-2">Show:</span>
            <Link
              href="/documents?filter=unlinked"
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                filter === 'unlinked'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted hover:bg-muted/80 text-muted-foreground'
              }`}
            >
              Unlinked
            </Link>
            <Link
              href="/documents?filter=linked"
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                filter === 'linked'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted hover:bg-muted/80 text-muted-foreground'
              }`}
            >
              Linked
            </Link>
            <Link
              href="/documents?filter=all"
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                filter === 'all'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted hover:bg-muted/80 text-muted-foreground'
              }`}
            >
              All
            </Link>
          </div>
        </div>
        
        {documents.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-muted-foreground text-lg">
              No documents found.
            </p>
            <p className="text-sm text-muted-foreground mt-2">
              Check back later for meeting minutes, agendas, and more.
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="border rounded-lg p-6 hover:border-primary/50 transition-colors"
              >
                <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      <span className="text-xs font-medium px-2 py-1 rounded-full bg-primary/10 text-primary">
                        {doc.source_name}
                      </span>
                      <span className={`text-xs font-medium px-2 py-1 rounded-full ${getDocumentTypeBadgeColor(doc.document_type)}`}>
                        {getDocumentTypeLabel(doc.document_type)}
                      </span>
                      {doc.event_count > 0 ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-green-100 text-green-700">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                          </svg>
                          {doc.event_count} event{doc.event_count !== 1 ? 's' : ''}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-amber-100 text-amber-700">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                          </svg>
                          Unlinked
                        </span>
                      )}
                      {doc.ai_summary && (
                        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-indigo-100 text-indigo-700">
                          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                          </svg>
                          ✨ AI Summary
                        </span>
                      )}
                    </div>
                    <h2 className="text-xl font-semibold mb-2">{doc.title}</h2>
                    {doc.content_text && (
                      <p className="text-muted-foreground mb-4">
                        {truncateText(doc.content_text)}
                      </p>
                    )}
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                      </svg>
                      <span>{formatDate(doc.published_date)}</span>
                    </div>
                  </div>
                  {doc.source_url && (
                    <div className="flex flex-col gap-2">
                      {/* Read button - links to document detail page */}
                      <Link
                        href={`/documents/${doc.id}`}
                        className="inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                      >
                        Read
                        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                      </Link>
                      
                      {/* Download button - prefers local file */}
                      {(doc.local_path || doc.source_url) && (
                        <a
                          href={doc.local_path ? `/api/files/${doc.local_path}` : doc.source_url!}
                          target={doc.local_path ? undefined : "_blank"}
                          rel={doc.local_path ? undefined : "noopener noreferrer"}
                          className="inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium rounded-md border hover:bg-accent transition-colors"
                        >
                          {doc.local_path ? 'Download' : 'View Source'}
                          {doc.local_path && doc.file_size_bytes && (
                            <span className="text-xs text-muted-foreground">
                              ({formatFileSize(doc.file_size_bytes)})
                            </span>
                          )}
                          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            {doc.local_path ? (
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                            ) : (
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                            )}
                          </svg>
                        </a>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
