import { NextResponse } from 'next/server';

export async function GET() {
  // Basic health check - can be extended to check database, etc.
  return NextResponse.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
  });
}
