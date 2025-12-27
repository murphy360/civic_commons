/**
 * Next.js Instrumentation Hook
 * Runs once when the Next.js server starts
 */

export function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    console.log('============================================================');
    console.log('WEB SERVICE STARTED - Public web app ready');
    console.log('============================================================');
    
    // Note: Activity log is handled by other services (API, Scraper)
    // Web just logs to console for visibility
  }
}

