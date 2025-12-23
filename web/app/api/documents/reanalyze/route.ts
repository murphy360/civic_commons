import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  try {
    const { documentId } = await request.json();

    if (!documentId || typeof documentId !== 'number') {
      return NextResponse.json(
        { error: 'Invalid documentId' },
        { status: 400 }
      );
    }

    // Check if document exists
    const doc = await sql`
      SELECT id FROM documents WHERE id = ${documentId}
    `;

    if (!doc || doc.length === 0) {
      return NextResponse.json(
        { error: 'Document not found' },
        { status: 404 }
      );
    }

    // Reset document to ai_pending status and clear AI summary to trigger re-analysis
    // Set summary_priority to NOW() to prioritize manually queued items
    await sql`
      UPDATE documents 
      SET content_status = 'ai_pending',
          ai_summary = NULL,
          ai_summary_updated_at = NULL,
          summary_priority = NOW()
      WHERE id = ${documentId}
    `;

    return NextResponse.json({
      success: true,
      message: 'Document queued for re-analysis',
      documentId,
    });
  } catch (error) {
    console.error('Failed to reanalyze document:', error);
    return NextResponse.json(
      { error: 'Failed to queue document for re-analysis' },
      { status: 500 }
    );
  }
}
