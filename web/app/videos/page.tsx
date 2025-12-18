import Link from 'next/link';
import { sql } from '@/lib/db';
import { Header } from '../components/Header';
import { LinkStatusBadge } from '../components/LinkStatusBadge';
import { AISummaryBadge } from '../components/AISummaryBadge';

export const dynamic = 'force-dynamic';

interface VideoDocument {
  id: number;
  title: string;
  source_url: string;
  published_date: Date | null;
  source_name: string;
  ai_summary: string | null;
  event_count: number;
  event_id: number | null;
  event_title: string | null;
}

type FilterType = 'all' | 'linked' | 'unlinked';

async function getVideos(filter: FilterType): Promise<VideoDocument[]> {
  try {
    let videos: VideoDocument[];
    
    if (filter === 'unlinked') {
      videos = await sql<VideoDocument[]>`
        SELECT 
          d.id,
          d.title,
          d.source_url,
          d.published_date,
          s.name as source_name,
          d.ai_summary,
          0 as event_count,
          NULL::int as event_id,
          NULL::text as event_title
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        WHERE d.document_type = 'video'
          AND NOT EXISTS (
            SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id
          )
        ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
        LIMIT 100
      `;
    } else if (filter === 'linked') {
      videos = await sql<VideoDocument[]>`
        SELECT 
          d.id,
          d.title,
          d.source_url,
          d.published_date,
          s.name as source_name,
          d.ai_summary,
          (SELECT COUNT(*) FROM event_documents ed WHERE ed.document_id = d.id)::int as event_count,
          (SELECT e.id FROM event_documents ed JOIN events e ON ed.event_id = e.id WHERE ed.document_id = d.id LIMIT 1)::int as event_id,
          (SELECT e.title FROM event_documents ed JOIN events e ON ed.event_id = e.id WHERE ed.document_id = d.id LIMIT 1) as event_title
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        WHERE d.document_type = 'video'
          AND EXISTS (
            SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id
          )
        ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
        LIMIT 100
      `;
    } else {
      videos = await sql<VideoDocument[]>`
        SELECT 
          d.id,
          d.title,
          d.source_url,
          d.published_date,
          s.name as source_name,
          d.ai_summary,
          (SELECT COUNT(*) FROM event_documents ed WHERE ed.document_id = d.id)::int as event_count,
          (SELECT e.id FROM event_documents ed JOIN events e ON ed.event_id = e.id WHERE ed.document_id = d.id LIMIT 1)::int as event_id,
          (SELECT e.title FROM event_documents ed JOIN events e ON ed.event_id = e.id WHERE ed.document_id = d.id LIMIT 1) as event_title
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        WHERE d.document_type = 'video'
        ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
        LIMIT 100
      `;
    }
    return videos;
  } catch (error) {
    console.error('Failed to fetch videos:', error);
    return [];
  }
}

async function getVideoCounts(): Promise<{ total: number; linked: number; unlinked: number }> {
  try {
    const result = await sql<{ total: number; linked: number; unlinked: number }[]>`
      SELECT 
        COUNT(*)::int as total,
        COUNT(CASE WHEN EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id) THEN 1 END)::int as linked,
        COUNT(CASE WHEN NOT EXISTS (SELECT 1 FROM event_documents ed WHERE ed.document_id = d.id) THEN 1 END)::int as unlinked
      FROM documents d
      WHERE d.document_type = 'video'
    `;
    return result[0] || { total: 0, linked: 0, unlinked: 0 };
  } catch (error) {
    console.error('Failed to fetch video counts:', error);
    return { total: 0, linked: 0, unlinked: 0 };
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

function getYouTubeThumbnail(url: string): string | null {
  const match = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\s?]+)/);
  return match ? `https://img.youtube.com/vi/${match[1]}/mqdefault.jpg` : null;
}

function VideoCard({ video }: { video: VideoDocument }) {
  const thumbnail = getYouTubeThumbnail(video.source_url);
  const isLinked = video.event_count > 0;

  return (
    <div className="block border rounded-lg overflow-hidden hover:border-primary/50 transition-colors bg-background">
      <div className="flex flex-col md:flex-row">
        {/* Thumbnail */}
        <a 
          href={video.source_url} 
          target="_blank" 
          rel="noopener noreferrer"
          className="relative md:w-64 h-36 bg-gray-900 flex-shrink-0 group"
        >
          {thumbnail ? (
            <img 
              src={thumbnail} 
              alt={video.title}
              className="w-full h-full object-cover"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-red-600 to-red-800">
              <svg className="h-16 w-16 text-white/80" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z"/>
              </svg>
            </div>
          )}
          {/* Play overlay */}
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="w-14 h-14 rounded-full bg-red-600 flex items-center justify-center">
              <svg className="h-8 w-8 text-white ml-1" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z"/>
              </svg>
            </div>
          </div>
        </a>

        {/* Content */}
        <div className="flex-1 p-4">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="text-xs font-medium px-2 py-1 rounded-full bg-primary/10 text-primary">
              {video.source_name}
            </span>
            <LinkStatusBadge documentId={video.id} eventCount={video.event_count} />
            <AISummaryBadge 
              documentId={video.id} 
              hasSummary={!!video.ai_summary}
              canSummarize={true}  // All videos on this page are YouTube videos
            />
          </div>

          <Link href={`/documents/${video.id}`}>
            <h2 className="text-lg font-semibold mb-2 hover:text-primary transition-colors">
              {video.title}
            </h2>
          </Link>

          <div className="flex flex-wrap items-center gap-4 text-sm text-muted-foreground mb-3">
            <div className="flex items-center gap-1">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span>{formatDate(video.published_date)}</span>
            </div>
          </div>

          {/* Linked event info */}
          {isLinked && video.event_id && (
            <div className="text-sm text-muted-foreground mb-3">
              <span>Linked to: </span>
              <Link href={`/events/${video.event_id}`} className="text-primary hover:underline">
                {video.event_title}
              </Link>
            </div>
          )}

          <div className="flex items-center gap-3">
            <a 
              href={video.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition-colors"
            >
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z"/>
              </svg>
              Watch Video
            </a>
            <Link 
              href={`/documents/${video.id}`}
              className="text-sm text-muted-foreground hover:text-primary transition-colors"
            >
              View Details →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export default async function VideosPage({
  searchParams,
}: {
  searchParams: { filter?: string };
}) {
  const filter = (searchParams.filter as FilterType) || 'all';
  const [videos, counts] = await Promise.all([
    getVideos(filter),
    getVideoCounts(),
  ]);

  return (
    <div className="flex flex-col min-h-screen">
      <Header />

      {/* Main Content */}
      <main className="container py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-3xl font-bold">📹 Meeting Videos</h1>
            <p className="text-muted-foreground mt-1">
              Watch recordings of city meetings and public hearings
            </p>
          </div>
        </div>

        {/* Filter Tabs */}
        <div className="flex items-center gap-1 border-b mb-6">
          <Link
            href="/videos?filter=all"
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              filter === 'all'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
            }`}
          >
            All Videos
            <span className={`ml-2 px-2 py-0.5 text-xs rounded-full ${
              filter === 'all' 
                ? 'bg-primary/10 text-primary' 
                : 'bg-muted text-muted-foreground'
            }`}>
              {counts.total}
            </span>
          </Link>
          <Link
            href="/videos?filter=linked"
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              filter === 'linked'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
            }`}
          >
            Linked to Events
            <span className={`ml-2 px-2 py-0.5 text-xs rounded-full ${
              filter === 'linked' 
                ? 'bg-primary/10 text-primary' 
                : 'bg-muted text-muted-foreground'
            }`}>
              {counts.linked}
            </span>
          </Link>
          <Link
            href="/videos?filter=unlinked"
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              filter === 'unlinked'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
            }`}
          >
            Unlinked
            <span className={`ml-2 px-2 py-0.5 text-xs rounded-full ${
              filter === 'unlinked' 
                ? 'bg-primary/10 text-primary' 
                : 'bg-muted text-muted-foreground'
            }`}>
              {counts.unlinked}
            </span>
          </Link>
        </div>

        {videos.length === 0 ? (
          <div className="text-center py-12 border rounded-lg bg-muted/20">
            <svg className="h-16 w-16 mx-auto text-muted-foreground/50 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <p className="text-muted-foreground text-lg">
              {filter === 'all' ? 'No videos available yet.' : 
               filter === 'linked' ? 'No linked videos found.' : 
               'No unlinked videos found.'}
            </p>
            <p className="text-sm text-muted-foreground mt-2">
              {filter === 'all' ? 'Videos will appear here as they become available.' :
               filter === 'linked' ? 'Videos linked to events will appear here.' :
               'All videos are currently linked to events.'}
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {videos.map((video) => (
              <VideoCard key={video.id} video={video} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
