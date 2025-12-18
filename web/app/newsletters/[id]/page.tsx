import Link from 'next/link';
import { sql } from '@/lib/db';
import { notFound } from 'next/navigation';
import { Header } from '../../components/Header';
import ReactMarkdown from 'react-markdown';

export const dynamic = 'force-dynamic';

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
  updated_at: Date;
  created_at: Date;
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

async function getSummary(id: number): Promise<Summary | null> {
  try {
    const summaries = await sql<Summary[]>`
      SELECT 
        id, city_id, title, summary_type, 
        period_start, period_end, status,
        summary_text, completeness_score,
        version, is_stale, updated_at, created_at
      FROM summaries
      WHERE id = ${id}
    `;
    return summaries[0] || null;
  } catch (error) {
    console.error('Failed to fetch summary:', error);
    return null;
  }
}

function formatDateRange(start: Date, end: Date, summaryType: string): string {
  const startDate = new Date(start);
  const endDate = new Date(end);
  
  const options: Intl.DateTimeFormatOptions = { 
    month: 'long', 
    day: 'numeric',
    year: 'numeric'
  };

  if (summaryType === 'daily') {
    return startDate.toLocaleDateString('en-US', options);
  }
  
  if (summaryType === 'annual') {
    return `Year ${startDate.getFullYear()}`;
  }

  return `${startDate.toLocaleDateString('en-US', { month: 'long', day: 'numeric' })} - ${endDate.toLocaleDateString('en-US', options)}`;
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const summary = await getSummary(parseInt(id, 10));
  
  if (!summary) {
    return { title: 'Summary Not Found' };
  }

  return {
    title: summary.title || `${PERIOD_LABELS[summary.summary_type]} Summary`,
    description: `${PERIOD_LABELS[summary.summary_type]} summary of civic activities.`,
  };
}

export default async function SummaryDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const summary = await getSummary(parseInt(id, 10));

  if (!summary) {
    notFound();
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Header />

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
              Back to Summaries
            </Link>
          </nav>

          {/* Summary Header */}
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-4">
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${PERIOD_COLORS[summary.summary_type]}`}>
                {PERIOD_LABELS[summary.summary_type]}
              </span>
              <span className="text-sm text-muted-foreground">
                {formatDateRange(summary.period_start, summary.period_end, summary.summary_type)}
              </span>
              {summary.is_stale && (
                <span className="px-2 py-1 rounded-full text-xs bg-yellow-100 text-yellow-800">
                  Update Pending
                </span>
              )}
            </div>
            <h1 className="text-3xl font-bold tracking-tight">
              {summary.title || formatDateRange(summary.period_start, summary.period_end, summary.summary_type)}
            </h1>
            <div className="flex items-center gap-6 mt-4 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Updated {new Date(summary.updated_at).toLocaleDateString('en-US', { 
                  month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'
                })}
              </span>
              <span>Version {summary.version}</span>
              {summary.completeness_score !== null && (
                <span className="flex items-center gap-1">
                  <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {Math.round(summary.completeness_score * 100)}% complete
                </span>
              )}
            </div>
          </div>

          {/* Summary Content */}
          {summary.summary_text ? (
            <article className="prose prose-neutral dark:prose-invert max-w-none bg-card rounded-lg border p-8">
              <ReactMarkdown>{summary.summary_text}</ReactMarkdown>
            </article>
          ) : (
            <div className="text-center py-12 bg-muted/50 rounded-lg">
              <p className="text-muted-foreground">Summary content is being generated...</p>
            </div>
          )}

          {/* Info Section */}
          <div className="mt-8 p-4 bg-muted/50 rounded-lg text-sm text-muted-foreground">
            <p>
              This summary updates automatically as new information becomes available. 
              When new documents are added to events within this period, the summary will be regenerated.
            </p>
          </div>
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
