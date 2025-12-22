import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

interface Legislation {
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
  year: number | null;
}

export async function GET() {
  try {
    // Get legislation with event counts from both event_documents and legislation_mentions
    const documents = await sql<Legislation[]>`
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
        (
          -- Count direct event links via event_documents
          (SELECT COUNT(*) FROM event_documents ed WHERE ed.document_id = d.id)
          +
          -- Count mentions in legislation_mentions by matching number pattern
          (SELECT COUNT(DISTINCT lm.event_id) 
           FROM legislation_mentions lm 
           WHERE lm.event_id IS NOT NULL
             AND (
               -- Match ordinance numbers like "44-24" to legislation_number
               (d.document_type = 'ordinance' AND lm.legislation_type = 'ordinance' 
                AND d.title ~ ('^' || lm.legislation_number || '[-:]'))
               OR
               -- Match resolution numbers
               (d.document_type = 'resolution' AND lm.legislation_type = 'resolution' 
                AND d.title ~ ('^' || lm.legislation_number || '[-:]'))
             )
          )
        )::int as event_count,
        EXTRACT(YEAR FROM d.published_date)::int as year
      FROM documents d
      JOIN sources s ON d.source_id = s.id
      WHERE d.document_type IN ('legislation', 'ordinance', 'resolution')
         OR s.name LIKE '%Legislation%'
      ORDER BY d.published_date DESC NULLS LAST, d.title ASC
    `;
    
    return NextResponse.json(documents);
  } catch (error) {
    console.error('Failed to fetch legislation:', error);
    return NextResponse.json({ error: 'Failed to fetch legislation' }, { status: 500 });
  }
}
