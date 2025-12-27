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

/**
 * Queue a periodic summary (annual, quarterly, monthly, weekly, daily) for (re)analysis.
 * If summaryId is provided, triggers regeneration of an existing summary.
 * If summaryType and periodStart are provided, creates a new pending summary or triggers regeneration.
 */
export async function prioritizePeriodicSummary(
  options: { summaryId: number } | { summaryType: string; periodStart: string }
): Promise<{ success: boolean; message: string; summaryId?: number }> {
  try {
    if ('summaryId' in options) {
      // Update existing summary to trigger regeneration
      const result = await sql`
        UPDATE summaries 
        SET status = 'pending',
            is_stale = true,
            generation_triggered_by = 'manual',
            error_message = NULL
        WHERE id = ${options.summaryId}
        RETURNING id, summary_type
      `;
      
      if (result.length === 0) {
        return { success: false, message: 'Summary not found' };
      }
      
      revalidatePath('/events');
      revalidatePath('/newsletters');
      
      return { 
        success: true, 
        message: `${result[0].summary_type} summary queued for re-analysis`,
        summaryId: result[0].id
      };
    } else {
      // Create or update summary by type and period
      const { summaryType, periodStart } = options;
      
      if (!['daily', 'weekly', 'monthly', 'quarterly', 'annual'].includes(summaryType)) {
        return { success: false, message: 'Invalid summary type' };
      }
      
      const startDate = new Date(periodStart);
      let endDate: Date;
      
      switch (summaryType) {
        case 'daily':
          endDate = new Date(startDate);
          endDate.setHours(23, 59, 59, 999);
          break;
        case 'weekly':
          endDate = new Date(startDate);
          endDate.setDate(endDate.getDate() + 6);
          endDate.setHours(23, 59, 59, 999);
          break;
        case 'monthly':
          endDate = new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0, 23, 59, 59, 999);
          break;
        case 'quarterly':
          endDate = new Date(startDate.getFullYear(), startDate.getMonth() + 3, 0, 23, 59, 59, 999);
          break;
        case 'annual':
          endDate = new Date(startDate.getFullYear(), 11, 31, 23, 59, 59, 999);
          break;
        default:
          endDate = new Date(startDate);
      }
      
      // Check if summary exists
      const existing = await sql<{ id: number }[]>`
        SELECT id FROM summaries
        WHERE summary_type = ${summaryType} 
          AND period_start = ${startDate.toISOString()}
          AND city_id = 'twinsburg'
      `;
      
      if (existing && existing.length > 0) {
        // Update existing
        await sql`
          UPDATE summaries 
          SET status = 'pending',
              is_stale = true,
              generation_triggered_by = 'manual',
              error_message = NULL
          WHERE id = ${existing[0].id}
        `;
        
        revalidatePath('/events');
        revalidatePath('/newsletters');
        
        return { 
          success: true, 
          message: `${summaryType} summary queued for re-analysis`,
          summaryId: existing[0].id
        };
      }
      
      // Create new pending summary
      const result = await sql<{ id: number }[]>`
        INSERT INTO summaries (
          city_id, summary_type, period_start, period_end, 
          status, generation_triggered_by
        ) VALUES (
          'twinsburg', 
          ${summaryType}, 
          ${startDate.toISOString()}, 
          ${endDate.toISOString()},
          'pending',
          'manual'
        )
        RETURNING id
      `;
      
      revalidatePath('/events');
      revalidatePath('/newsletters');
      
      return { 
        success: true, 
        message: `${summaryType} summary created and queued for generation`,
        summaryId: result[0].id
      };
    }
  } catch (error) {
    console.error('Failed to queue summary for analysis:', error);
    return { success: false, message: 'Failed to queue summary for analysis' };
  }
}
