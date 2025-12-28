import { NextResponse } from 'next/server';
export const dynamic = 'force-dynamic';

const BACKEND_API_URL = process.env.INTERNAL_API_URL || 'http://commons-api:8080';
const CITY_ID = 'twinsburg';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const params = new URLSearchParams();
    params.append('city_id', CITY_ID);
    for (const [key, value] of Array.from(searchParams.entries())) {
      if (key !== 'city_id') params.append(key, value);
    }
    const endpoint = '/admin/ai-logs';
    const url = BACKEND_API_URL + endpoint + '?' + params.toString();
    const response = await fetch(url, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error('Backend error');
    return NextResponse.json(await response.json());
  } catch (error) {
    console.error('Proxy error:', error);
    return NextResponse.json({ error: 'Proxy error' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const params = new URLSearchParams();
    params.append('city_id', CITY_ID);
    const endpoint = '/admin/ai-logs';
    const url = BACKEND_API_URL + endpoint + '?' + params.toString();
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error('Backend error');
    return NextResponse.json(await response.json());
  } catch (error) {
    console.error('Proxy error:', error);
    return NextResponse.json({ error: 'Proxy error' }, { status: 500 });
  }
}
