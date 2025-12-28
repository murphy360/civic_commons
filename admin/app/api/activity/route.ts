import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const BACKEND_API_URL = process.env.INTERNAL_API_URL || 'http://commons-api:8080';
const CITY_ID = 'twinsburg'; // Admin dashboard is currently single-city

/**
 * GET /api/activity
 * Proxy to backend /admin/activity
 */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const params = new URLSearchParams();
    params.append('city_id', CITY_ID);
    for (const [key, value] of Array.from(searchParams.entries())) {
      if (key !== 'city_id') params.append(key, value);
    }

    const response = await fetch(`${BACKEND_API_URL}/admin/activity?${params}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Failed to proxy activity:', error);
    return NextResponse.json(
      { error: 'Failed to fetch activity logs', activities: [] },
      { status: 500 }
    );
  }
}
