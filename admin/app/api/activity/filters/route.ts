import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const BACKEND_API_URL = process.env.INTERNAL_API_URL || 'http://commons-api:8080';
const CITY_ID = 'twinsburg';

export async function GET() {
  try {
    const endpoint = '/admin/activity/filters';
    const url = BACKEND_API_URL + endpoint + '?city_id=' + CITY_ID;
    const response = await fetch(url, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) throw new Error('Backend error');
    const data = await response.json();

    return NextResponse.json({
      categories: data.categories || [],
      levels: data.levels || [],
      category_icons: data.category_icons || {
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
      category_labels: data.category_labels || {
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
    console.error('Proxy error:', error);
    return NextResponse.json({ error: 'Proxy error' }, { status: 500 });
  }
}
