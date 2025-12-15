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
}

async function getDocuments(): Promise<Document[]> {
  try {
    const documents = await sql<Document[]>`
      SELECT 
        d.id,
        d.title,
        d.document_type,
        d.content_text,
        d.source_url,
        d.local_path,
        d.file_size_bytes,
        d.published_date,
        s.name as source_name
      FROM documents d
      JOIN sources s ON d.source_id = s.id
      ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
      LIMIT 50
    `;
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

export default async function DocumentsPage() {
  const documents = await getDocuments();

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
        <h1 className="text-3xl font-bold mb-8">Documents</h1>
        
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
