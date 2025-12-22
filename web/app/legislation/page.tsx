'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Header } from '../components/Header';

interface Legislation {
  id: number;
  title: string;
  document_type: string | null;
  content_text: string | null;
  source_url: string | null;
  local_path: string | null;
  file_size_bytes: number | null;
  published_date: string | null;
  source_name: string;
  ai_summary: string | null;
  event_count: number;
  year: number | null;
}

interface LegislationByYear {
  year: number;
  documents: Legislation[];
}

function groupByYear(documents: Legislation[]): LegislationByYear[] {
  const grouped = new Map<number, Legislation[]>();
  
  for (const doc of documents) {
    // Try to extract year from title pattern like "34-24" or "12-25"
    const titleMatch = doc.title.match(/-(\d{2})[\s:]/);
    let year = doc.year;
    
    if (titleMatch) {
      const twoDigitYear = parseInt(titleMatch[1], 10);
      year = twoDigitYear >= 90 ? 1900 + twoDigitYear : 2000 + twoDigitYear;
    }
    
    const displayYear = year || new Date().getFullYear();
    
    if (!grouped.has(displayYear)) {
      grouped.set(displayYear, []);
    }
    grouped.get(displayYear)!.push(doc);
  }
  
  // Sort years descending (newest first)
  const sortedYears = Array.from(grouped.keys()).sort((a, b) => b - a);
  
  return sortedYears.map(year => ({
    year,
    documents: grouped.get(year)!,
  }));
}

function formatDate(date: string | null): string {
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

function truncateText(text: string | null, maxLength: number = 200): string {
  if (!text) return '';
  if (text.length <= maxLength) return text;
  return text.substring(0, maxLength).trim() + '...';
}

// Extract the legislation number from title (e.g., "34-24" from "34-24: Appropriations...")
function getLegislationNumber(title: string): string | null {
  const match = title.match(/^(\d+-\d+)/);
  return match ? match[1] : null;
}

// Collapsible Year Section Component
function YearSection({ year, documents, defaultExpanded }: { 
  year: number; 
  documents: Legislation[]; 
  defaultExpanded: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const linkedCount = documents.filter(d => d.event_count > 0).length;
  const summarizedCount = documents.filter(d => d.ai_summary).length;

  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Year Header - Clickable */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 bg-muted/30 hover:bg-muted/50 transition-colors text-left"
      >
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <svg 
              className={`w-5 h-5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} 
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            <h2 className="text-xl font-semibold">{year} Legislation</h2>
          </div>
          <span className="text-sm text-muted-foreground bg-background px-2 py-1 rounded">
            {documents.length} document{documents.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {linkedCount > 0 && (
            <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-green-100 text-green-700">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
              {linkedCount} linked
            </span>
          )}
          {summarizedCount > 0 && (
            <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-indigo-100 text-indigo-700">
              ✨ {summarizedCount} summarized
            </span>
          )}
        </div>
      </button>
      
      {/* Expandable Content */}
      {isExpanded && (
        <div className="p-4 border-t">
          <div className="grid gap-3">
            {documents.map((doc) => (
              <LegislationCard key={doc.id} doc={doc} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// Individual Legislation Card Component
function LegislationCard({ doc }: { doc: Legislation }) {
  const legNumber = getLegislationNumber(doc.title);
  
  return (
    <div className="border rounded-lg p-4 hover:border-primary/50 transition-colors">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            {legNumber && (
              <span className="text-sm font-mono font-bold px-2 py-0.5 rounded bg-purple-100 text-purple-800">
                #{legNumber}
              </span>
            )}
            <span className="text-xs font-medium px-2 py-1 rounded-full bg-primary/10 text-primary">
              {doc.source_name}
            </span>
            {doc.event_count > 0 && (
              <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full bg-green-100 text-green-700">
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
                {doc.event_count} event{doc.event_count !== 1 ? 's' : ''}
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
          <h3 className="text-lg font-medium mb-1">
            {legNumber ? doc.title.replace(/^\d+-\d+:\s*/, '') : doc.title}
          </h3>
          {doc.ai_summary ? (
            <p className="text-muted-foreground text-sm mb-2">
              {truncateText(doc.ai_summary, 300)}
            </p>
          ) : doc.content_text && (
            <p className="text-muted-foreground text-sm mb-2">
              {truncateText(doc.content_text, 150)}
            </p>
          )}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span>{formatDate(doc.published_date)}</span>
          </div>
        </div>
        <div className="flex flex-row md:flex-col gap-2">
          {/* Read button - links to document detail page */}
          <Link
            href={`/documents/${doc.id}`}
            className="inline-flex items-center justify-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
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
              className="inline-flex items-center justify-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md border hover:bg-accent transition-colors"
            >
              {doc.local_path ? 'PDF' : 'Source'}
              {doc.local_path && doc.file_size_bytes && (
                <span className="text-xs text-muted-foreground">
                  ({formatFileSize(doc.file_size_bytes)})
                </span>
              )}
              <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {doc.local_path ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                )}
              </svg>
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

export default function LegislationPage() {
  const [allLegislation, setAllLegislation] = useState<Legislation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchLegislation() {
      try {
        const response = await fetch('/api/legislation');
        if (!response.ok) throw new Error('Failed to fetch legislation');
        const data = await response.json();
        setAllLegislation(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }
    fetchLegislation();
  }, []);

  const legislationByYear = groupByYear(allLegislation);
  const currentYear = new Date().getFullYear();

  if (loading) {
    return (
      <div className="flex flex-col min-h-screen">
        <Header />
        <main className="container py-8">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-gray-200 rounded w-1/4"></div>
            <div className="h-4 bg-gray-200 rounded w-1/3"></div>
            <div className="space-y-3 mt-8">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-24 bg-gray-200 rounded"></div>
              ))}
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-screen">
      <Header />

      {/* Main Content */}
      <main className="container py-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-bold">Legislation</h1>
            <p className="text-muted-foreground mt-1">
              Ordinances, resolutions, and other legislative documents
            </p>
          </div>
          <div className="text-sm text-muted-foreground">
            {allLegislation.length} document{allLegislation.length !== 1 ? 's' : ''}
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-6">
            Error: {error}
          </div>
        )}
        
        {legislationByYear.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-muted-foreground text-lg">
              No legislation found.
            </p>
            <p className="text-sm text-muted-foreground mt-2">
              Check back later for ordinances, resolutions, and other legislative documents.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {legislationByYear.map(({ year, documents }, index) => (
              <YearSection 
                key={year} 
                year={year} 
                documents={documents} 
                defaultExpanded={year === currentYear || index === 0}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
