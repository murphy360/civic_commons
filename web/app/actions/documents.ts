'use server';

import { sql } from '@/lib/db';
import { revalidatePath } from 'next/cache';

export async function reprocessDocument(documentId: number): Promise<{ success: boolean; message: string }> {
  try {
    // Reset linking status to 'pending' so the AI queue will reprocess it
    const result = await sql`
      UPDATE documents 
      SET linking_status = 'pending',
          updated_at = NOW()
      WHERE id = ${documentId}
      RETURNING id, title
    `;
    
    if (result.length === 0) {
      return { success: false, message: 'Document not found' };
    }
    
    // Revalidate both documents and videos pages
    revalidatePath('/documents');
    revalidatePath('/videos');
    
    return { 
      success: true, 
      message: `Queued "${result[0].title}" for reprocessing` 
    };
  } catch (error) {
    console.error('Failed to queue document for reprocessing:', error);
    return { success: false, message: 'Failed to queue document for reprocessing' };
  }
}

export async function prioritizeSummary(documentId: number): Promise<{ success: boolean; message: string }> {
  try {
    // Set summary_priority to current timestamp to push it to front of queue
    // The AI queue will order by summary_priority DESC NULLS LAST
    const result = await sql`
      UPDATE documents 
      SET summary_priority = NOW(),
          updated_at = NOW()
      WHERE id = ${documentId}
      RETURNING id, title
    `;
    
    if (result.length === 0) {
      return { success: false, message: 'Document not found' };
    }
    
    // Revalidate both documents and videos pages
    revalidatePath('/documents');
    revalidatePath('/videos');
    
    return { 
      success: true, 
      message: `Prioritized "${result[0].title}" for AI summary` 
    };
  } catch (error) {
    console.error('Failed to prioritize document for summary:', error);
    return { success: false, message: 'Failed to prioritize document for summary' };
  }
}
