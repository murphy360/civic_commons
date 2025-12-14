import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const query = searchParams.get('q');

    let documents;
    
    if (query) {
      // Full-text search
      documents = await sql`
        SELECT 
          d.id,
          d.title,
          d.document_type,
          d.content_text,
          d.source_url,
          d.published_date,
          s.name as source_name,
          ts_rank(d.search_vector, plainto_tsquery('english', ${query})) as rank
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        WHERE d.search_vector @@ plainto_tsquery('english', ${query})
        ORDER BY rank DESC, d.published_date DESC
        LIMIT 50
      `;
    } else {
      // Recent documents
      documents = await sql`
        SELECT 
          d.id,
          d.title,
          d.document_type,
          d.content_text,
          d.source_url,
          d.published_date,
          s.name as source_name
        FROM documents d
        JOIN sources s ON d.source_id = s.id
        ORDER BY d.published_date DESC NULLS LAST, d.created_at DESC
        LIMIT 50
      `;
    }

    return NextResponse.json({ documents });
  } catch (error) {
    console.error('Failed to fetch documents:', error);
    return NextResponse.json(
      { error: 'Failed to fetch documents' },
      { status: 500 }
    );
  }
}
