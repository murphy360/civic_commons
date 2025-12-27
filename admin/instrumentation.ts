/**
 * Next.js Instrumentation Hook
 * Runs once when the Next.js server starts
 */

export function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    console.log('============================================================');
    console.log('ADMIN SERVICE STARTED - Admin dashboard ready');
    console.log('============================================================');
    
    // Note: Activity log is handled by other services (API, Scraper)
    // Admin just logs to console for visibility
  }
}

