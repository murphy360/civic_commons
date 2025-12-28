import { NextResponse } from 'next/server';
import { sql } from '@/lib/db';

export const dynamic = 'force-dynamic';

/**
 * GET /api/activity/filters
 * Returns available categories and levels for activity log filtering
 */
export async function GET() {
  try {
    // Get distinct categories from activity_log
    const categories = await sql`
      SELECT DISTINCT category FROM activity_log 
      WHERE category IS NOT NULL
      ORDER BY category
    `;
    
    // Get distinct levels from activity_log
    const levels = await sql`
      SELECT DISTINCT level FROM activity_log 
      WHERE level IS NOT NULL
      ORDER BY level
    `;
    
    const categoryList = categories.map((row) => row.category);
    const levelList = levels.map((row) => row.level);
    
    return NextResponse.json({
      categories: categoryList,
      levels: levelList,
      category_icons: {
        download: '⬇️',
        extraction: '📄',
        ai: '🤖',
        scrape: '🔄',
        event: '📅',
        tool_call: '🔧',
        mcp: '🧠',
        linking: '🔗',
        summary: '📝',
        system: '⚙️',
        error: '❌',
        api: '🌐',
      },
      category_labels: {
        download: 'Downloads',
        extraction: 'Extractions',
        ai: 'AI Analysis',
        scrape: 'Scraping',
        event: 'Events',
        tool_call: 'Tool Calls',
        mcp: 'MCP',
        linking: 'Linking',
        summary: 'Summaries',
        system: 'System',
        error: 'Errors',
        api: 'API Calls',
      },
    });
  } catch (error) {
    console.error('Failed to get activity filters:', error);
    return NextResponse.json({
      categories: [],
      levels: ['error', 'warning', 'info', 'success'],
      category_icons: {},
      category_labels: {},
    });
  }
}
