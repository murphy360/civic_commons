import Link from 'next/link';
import { sql } from '@/lib/db';
import { Header } from '../components/Header';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Summaries',
  description: 'AI-generated community summaries of local events and civic activities.',
};

interface Summary {
  id: number;
  city_id: string;
  title: string;
  summary_type: string;
  period_start: Date;
  period_end: Date;
  status: string;
  summary_text: string | null;
  completeness_score: number | null;
  version: number;
  is_stale: boolean;
  created_at: Date;
  updated_at: Date;
}

const PERIOD_LABELS: Record<string, string> = {
  event: 'Event',
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
  quarterly: 'Quarterly',
  annual: 'Annual',
};

const PERIOD_COLORS: Record<string, string> = {
  event: 'bg-gray-100 text-gray-800',
  daily: 'bg-blue-100 text-blue-800',
  weekly: 'bg-green-100 text-green-800',
  monthly: 'bg-purple-100 text-purple-800',
  quarterly: 'bg-orange-100 text-orange-800',
  annual: 'bg-red-100 text-red-800',
};

async function getSummaries(): Promise<Summary[]> {
  try {
    // Query the new summaries table, excluding event-level summaries
    const summaries = await sql<Summary[]>`
      SELECT 
        id, city_id, title, summary_type, 
        period_start, period_end, status,
        summary_text, completeness_score,
        version, is_stale, created_at, updated_at
      FROM summaries
      WHERE status = 'completed'
        AND event_id IS NULL
        AND summary_type != 'event'
      ORDER BY period_start DESC
      LIMIT 50
    `;
    return summaries;
  } catch (error) {
    console.error('Failed to fetch summaries:', error);
    return [];
  }
}

function formatDateRange(start: Date, end: Date, summaryType: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  
  const options: Intl.DateTimeFormatOptions = { 
    month: 'short', 
    day: 'numeric',
    year: 'numeric'
  };

  if (summaryType === 'daily') {
    return startDate.toLocaleDateString('en-US', options);
  }
  
  if (summaryType === 'annual') {
    return startDate.getFullYear().toString();
  }

  return `${startDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${endDate.toLocaleDateString('en-US', options)}`;
}

export default async function NewslettersPage() {
  const summaries = await getSummaries();

  // Group summaries by type
  const grouped = summaries.reduce((acc, summary) => {
    const type = summary.summary_type;
    if (!acc[type]) {
      acc[type] = [];
    }
    acc[type].push(summary);
    return acc;
  }, {} as Record<string, Summary[]>);

  const periodOrder = ['daily', 'weekly', 'monthly', 'quarterly', 'annual'];

  return (
    <div className="flex flex-col min-h-screen">
      <Header />

      {/* Main Content */}
      <main className="container py-8">
        <div className="flex flex-col gap-6">
          {/* Page Header */}
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Community Summaries</h1>
            <p className="text-muted-foreground mt-2">
              AI-generated summaries of community events and civic activities. 
              Updated automatically as new information arrives.
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

          {/* Summary Grid */}
          {summaries.length === 0 ? (
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
              <h3 className="text-lg font-semibold">No summaries yet</h3>
              <p className="text-muted-foreground mt-1">
                Summaries are generated automatically as events are processed. Check back soon!
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
                      <span>Summaries</span>
                    </h2>
                    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                      {items.map((summary) => (
                        <Link
                          key={summary.id}
                          href={`/newsletters/${summary.id}`}
                          className="group block p-6 rounded-lg border bg-card hover:border-primary/50 hover:shadow-md transition-all"
                        >
                          <div className="flex items-start justify-between mb-3">
                            <span className={`px-2 py-1 rounded text-xs ${PERIOD_COLORS[summary.summary_type]}`}>
                              {PERIOD_LABELS[summary.summary_type]}
                            </span>
                            <div className="flex items-center gap-2">
                              {summary.is_stale && (
                                <span className="text-xs text-yellow-600" title="Update pending">
                                  ⏳
                                </span>
                              )}
                              {summary.version > 1 && (
                                <span className="text-xs text-muted-foreground">
                                  v{summary.version}
                                </span>
                              )}
                            </div>
                          </div>
                          <h3 className="font-semibold text-lg group-hover:text-primary transition-colors">
                            {summary.title || formatDateRange(summary.period_start, summary.period_end, summary.summary_type)}
                          </h3>
                          <p className="text-sm text-muted-foreground mt-1">
                            {formatDateRange(summary.period_start, summary.period_end, summary.summary_type)}
                          </p>
                          <div className="flex items-center gap-4 mt-4 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                              </svg>
                              Updated {new Date(summary.updated_at).toLocaleDateString()}
                            </span>
                            {summary.completeness_score !== null && (
                              <span className="flex items-center gap-1">
                                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                                </svg>
                                {Math.round(summary.completeness_score * 100)}%
                              </span>
                            )}
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
