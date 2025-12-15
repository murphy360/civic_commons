import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * Get a single document by ID with related events
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const documentId = parseInt(id, 10);

    if (isNaN(documentId)) {
      return NextResponse.json(
        { error: 'Invalid document ID' },
        { status: 400 }
      );
    }

    // Get document details
    const documents = await sql`
      SELECT 
        d.id,
        d.title,
        d.document_type,
        d.content_text,
        d.content_markdown,
        d.source_url,
        d.file_url,
        d.local_path,
        d.file_hash,
        d.file_size_bytes,
        d.mime_type,
        d.published_date,
        d.created_at,
        d.updated_at,
        s.name as source_name,
        s.id as source_id
      FROM documents d
      JOIN sources s ON d.source_id = s.id
      WHERE d.id = ${documentId}
    `;

    if (documents.length === 0) {
      return NextResponse.json(
        { error: 'Document not found' },
        { status: 404 }
      );
    }

    const document = documents[0];

    // Get related events
    const events = await sql`
      SELECT 
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.location,
        e.source_url,
        ed.relationship
      FROM events e
      JOIN event_documents ed ON e.id = ed.event_id
      WHERE ed.document_id = ${documentId}
      ORDER BY e.start_time DESC
    `;

    return NextResponse.json({
      document: {
        ...document,
        events,
      },
    });
  } catch (error) {
    console.error('Failed to fetch document:', error);
    return NextResponse.json(
      { error: 'Failed to fetch document' },
      { status: 500 }
    );
  }
}
