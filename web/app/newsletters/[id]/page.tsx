import Link from 'next/link';
import { sql } from '@/lib/db';
import { notFound } from 'next/navigation';

export const dynamic = 'force-dynamic';

interface Newsletter {
  id: number;
  city_id: string;
  title: string;
  period_type: string;
  period_start: Date;
  period_end: Date;
  status: string;
  summary_text: string | null;
  pdf_url: string | null;
  event_count: number;
  document_count: number;
  metadata: Record<string, unknown> | null;
  created_at: Date;
}

const PERIOD_LABELS: Record<string, string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  annual: 'Annual',
};

const PERIOD_COLORS: Record<string, string> = {
  daily: 'bg-blue-100 text-blue-800',
  weekly: 'bg-green-100 text-green-800',
  monthly: 'bg-purple-100 text-purple-800',
  quarterly: 'bg-orange-100 text-orange-800',
  annual: 'bg-red-100 text-red-800',
};

async function getNewsletter(id: number): Promise<Newsletter | null> {
  try {
    const newsletters = await sql<Newsletter[]>`
      SELECT 
        id, city_id, title, period_type, 
        period_start, period_end, status,
        summary_text, pdf_url,
        event_count, document_count, metadata, created_at
      FROM newsletters
      WHERE id = ${id}
    `;
    return newsletters[0] || null;
  } catch (error) {
    console.error('Failed to fetch newsletter:', error);
    return null;
  }
}

function formatDateRange(start: Date, end: Date, periodType: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  
  const options: Intl.DateTimeFormatOptions = { 
    month: 'long', 
    day: 'numeric',
    year: 'numeric'
  };

  if (periodType === 'daily') {
    return startDate.toLocaleDateString('en-US', options);
  }
  
  if (periodType === 'annual') {
    return `Year ${startDate.getFullYear()}`;
  }

  return `${startDate.toLocaleDateString('en-US', { month: 'long', day: 'numeric' })} - ${endDate.toLocaleDateString('en-US', options)}`;
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const newsletter = await getNewsletter(parseInt(id, 10));
  
  if (!newsletter) {
    return { title: 'Newsletter Not Found' };
  }

  return {
    title: newsletter.title,
    description: `${PERIOD_LABELS[newsletter.period_type]} newsletter covering ${newsletter.event_count} events.`,
  };
}

export default async function NewsletterDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const newsletter = await getNewsletter(parseInt(id, 10));

  if (!newsletter) {
    notFound();
  }

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
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Documents
            </Link>
            <Link
              href="/newsletters"
              className="transition-colors hover:text-foreground/80 text-foreground"
            >
              Newsletters
            </Link>
          </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="container py-8">
        <div className="max-w-4xl mx-auto">
          {/* Breadcrumb */}
          <nav className="mb-6">
            <Link
              href="/newsletters"
              className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              Back to Newsletters
            </Link>
          </nav>

          {/* Newsletter Header */}
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-4">
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${PERIOD_COLORS[newsletter.period_type]}`}>
                {PERIOD_LABELS[newsletter.period_type]}
              </span>
              <span className="text-sm text-muted-foreground">
                {formatDateRange(newsletter.period_start, newsletter.period_end, newsletter.period_type)}
              </span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">{newsletter.title}</h1>
            <div className="flex items-center gap-6 mt-4 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
                {newsletter.event_count} events covered
              </span>
              <span className="flex items-center gap-1">
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                {newsletter.document_count} documents referenced
              </span>
            </div>
          </div>

          {/* PDF Download Button */}
          {newsletter.pdf_url && (
            <div className="mb-8">
              <a
                href={newsletter.pdf_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Download PDF
              </a>
            </div>
          )}

          {/* Newsletter Content */}
          {newsletter.summary_text ? (
            <article className="prose prose-neutral dark:prose-invert max-w-none">
              <div 
                className="bg-card rounded-lg border p-8"
                dangerouslySetInnerHTML={{ 
                  __html: newsletter.summary_text
                    .replace(/\n\n/g, '</p><p>')
                    .replace(/\n/g, '<br/>')
                    .replace(/^/, '<p>')
                    .replace(/$/, '</p>')
                    .replace(/## (.*?)(<br\/>|<\/p>)/g, '</p><h2>$1</h2><p>')
                    .replace(/### (.*?)(<br\/>|<\/p>)/g, '</p><h3>$1</h3><p>')
                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                    .replace(/\*(.*?)\*/g, '<em>$1</em>')
                }}
              />
            </article>
          ) : (
            <div className="text-center py-12 bg-muted/50 rounded-lg">
              <p className="text-muted-foreground">Newsletter content is being generated...</p>
            </div>
          )}

          {/* Metadata Section */}
          {newsletter.metadata && Object.keys(newsletter.metadata).length > 0 && (
            <div className="mt-8 p-6 bg-muted/50 rounded-lg">
              <h2 className="font-semibold mb-4">Additional Information</h2>
              <pre className="text-sm text-muted-foreground overflow-auto">
                {JSON.stringify(newsletter.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t py-6 md:py-0 mt-auto">
        <div className="container flex flex-col items-center justify-between gap-4 md:h-24 md:flex-row">
          <p className="text-center text-sm leading-loose text-muted-foreground md:text-left">
            Built for the community. Data sourced from official public records.
          </p>
          <p className="text-center text-sm text-muted-foreground">
            © {new Date().getFullYear()} Civic Commons
          </p>
        </div>
      </footer>
    </div>
  );
}
