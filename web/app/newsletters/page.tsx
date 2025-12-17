import Link from 'next/link';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Newsletters',
  description: 'AI-generated community newsletters summarizing local events and civic activities.',
};

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

async function getNewsletters(): Promise<Newsletter[]> {
  try {
    const newsletters = await sql<Newsletter[]>`
      SELECT 
        id, city_id, title, period_type, 
        period_start, period_end, status,
        summary_text, pdf_url,
        event_count, document_count, created_at
      FROM newsletters
      WHERE status = 'completed'
      ORDER BY period_start DESC
      LIMIT 50
    `;
    return newsletters;
  } catch (error) {
    console.error('Failed to fetch newsletters:', error);
    return [];
  }
}

function formatDateRange(start: Date, end: Date, periodType: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  
  const options: Intl.DateTimeFormatOptions = { 
    month: 'short', 
    day: 'numeric',
    year: 'numeric'
  };

  if (periodType === 'daily') {
    return startDate.toLocaleDateString('en-US', options);
  }
  
  if (periodType === 'annual') {
    return startDate.getFullYear().toString();
  }

  return `${startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${endDate.toLocaleDateString('en-US', options)}`;
}

export default async function NewslettersPage() {
  const newsletters = await getNewsletters();

  // Group newsletters by period type
  const grouped = newsletters.reduce((acc, newsletter) => {
    const type = newsletter.period_type;
    if (!acc[type]) {
      acc[type] = [];
    }
    acc[type].push(newsletter);
    return acc;
  }, {} as Record<string, Newsletter[]>);

  const periodOrder = ['daily', 'weekly', 'monthly', 'quarterly', 'annual'];

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
              href="/legislation"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Legislation
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
        <div className="flex flex-col gap-6">
          {/* Page Header */}
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Newsletters</h1>
            <p className="text-muted-foreground mt-2">
              AI-generated summaries of community events and civic activities.
            </p>
          </div>

          {/* Period Type Filter Tabs */}
          <div className="flex flex-wrap gap-2 border-b pb-4">
            <Link
              href="/newsletters"
              className="px-4 py-2 rounded-full text-sm font-medium bg-primary text-primary-foreground"
            >
              All
            </Link>
            {periodOrder.map((type) => (
              <Link
                key={type}
                href={`/newsletters?period=${type}`}
                className={`px-4 py-2 rounded-full text-sm font-medium ${PERIOD_COLORS[type]} hover:opacity-80 transition-opacity`}
              >
                {PERIOD_LABELS[type]}
              </Link>
            ))}
          </div>

          {/* Newsletter Grid */}
          {newsletters.length === 0 ? (
            <div className="text-center py-12">
              <div className="mx-auto w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
                <svg
                  className="h-8 w-8 text-muted-foreground"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z"
                  />
                </svg>
              </div>
              <h3 className="text-lg font-semibold">No newsletters yet</h3>
              <p className="text-muted-foreground mt-1">
                Newsletters are generated automatically. Check back soon!
              </p>
            </div>
          ) : (
            <div className="space-y-8">
              {periodOrder.map((periodType) => {
                const items = grouped[periodType];
                if (!items || items.length === 0) return null;

                return (
                  <section key={periodType}>
                    <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
                      <span className={`px-2 py-1 rounded text-xs ${PERIOD_COLORS[periodType]}`}>
                        {PERIOD_LABELS[periodType]}
                      </span>
                      <span>Newsletters</span>
                    </h2>
                    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                      {items.map((newsletter) => (
                        <Link
                          key={newsletter.id}
                          href={`/newsletters/${newsletter.id}`}
                          className="group block p-6 rounded-lg border bg-card hover:border-primary/50 hover:shadow-md transition-all"
                        >
                          <div className="flex items-start justify-between mb-3">
                            <span className={`px-2 py-1 rounded text-xs ${PERIOD_COLORS[newsletter.period_type]}`}>
                              {PERIOD_LABELS[newsletter.period_type]}
                            </span>
                            {newsletter.pdf_url && (
                              <span className="text-xs text-muted-foreground flex items-center gap-1">
                                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                </svg>
                                PDF
                              </span>
                            )}
                          </div>
                          <h3 className="font-semibold text-lg group-hover:text-primary transition-colors">
                            {newsletter.title}
                          </h3>
                          <p className="text-sm text-muted-foreground mt-1">
                            {formatDateRange(newsletter.period_start, newsletter.period_end, newsletter.period_type)}
                          </p>
                          <div className="flex items-center gap-4 mt-4 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                              </svg>
                              {newsletter.event_count} events
                            </span>
                            <span className="flex items-center gap-1">
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                              </svg>
                              {newsletter.document_count} docs
                            </span>
                          </div>
                        </Link>
                      ))}
                    </div>
                  </section>
                );
              })}
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
