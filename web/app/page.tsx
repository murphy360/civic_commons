import Link from 'next/link';

export default function HomePage() {
  return (
    <div className="flex flex-col min-h-screen">
      {/* Header */}
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container flex h-14 items-center">
          <div className="mr-4 flex">
            <Link href="/" className="mr-6 flex items-center space-x-2">
              <span className="font-bold text-xl">Civic Commons</span>
            </Link>
          </div>
          <nav className="flex items-center space-x-6 text-sm font-medium">
            <Link
              href="/events"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Events
            </Link>
            <Link
              href="/documents"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Documents
            </Link>
            <Link
              href="/legislation"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Legislation
            </Link>
            <Link
              href="/newsletters"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Newsletters
            </Link>
            <Link
              href="/search"
              className="transition-colors hover:text-foreground/80 text-foreground/60"
            >
              Search
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero Section */}
      <section className="container flex flex-col items-center justify-center gap-4 py-24 md:py-32">
        <h1 className="text-center text-3xl font-bold leading-tight tracking-tighter md:text-6xl lg:leading-[1.1]">
          Your Community,
          <br />
          <span className="text-primary">At Your Fingertips</span>
        </h1>
        <p className="max-w-[750px] text-center text-lg text-muted-foreground sm:text-xl">
          Find local events, meeting minutes, and civic documents. 
          Ask questions and get answers about what&apos;s happening in your community.
        </p>
        <div className="flex gap-4 mt-4">
          <Link
            href="/events"
            className="inline-flex items-center justify-center rounded-md bg-primary px-8 py-3 text-sm font-medium text-primary-foreground shadow transition-colors hover:bg-primary/90"
          >
            View Events
          </Link>
          <Link
            href="/search"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-8 py-3 text-sm font-medium shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            Search Documents
          </Link>
        </div>
      </section>

      {/* Features Section */}
      <section className="container py-12 md:py-24">
        <div className="grid gap-8 md:grid-cols-3">
          <div className="flex flex-col items-center text-center p-6">
            <div className="mb-4 rounded-full bg-primary/10 p-4">
              <svg
                className="h-6 w-6 text-primary"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                />
              </svg>
            </div>
            <h3 className="text-xl font-bold">Community Events</h3>
            <p className="mt-2 text-muted-foreground">
              Stay up to date with city council meetings, library programs, 
              parks events, and more.
            </p>
          </div>
          <div className="flex flex-col items-center text-center p-6">
            <div className="mb-4 rounded-full bg-primary/10 p-4">
              <svg
                className="h-6 w-6 text-primary"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            </div>
            <h3 className="text-xl font-bold">Official Documents</h3>
            <p className="mt-2 text-muted-foreground">
              Access meeting minutes, agendas, ordinances, and public records 
              all in one place.
            </p>
          </div>
          <div className="flex flex-col items-center text-center p-6">
            <div className="mb-4 rounded-full bg-primary/10 p-4">
              <svg
                className="h-6 w-6 text-primary"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
                />
              </svg>
            </div>
            <h3 className="text-xl font-bold">Ask Questions</h3>
            <p className="mt-2 text-muted-foreground">
              Chat with our AI assistant to find information quickly and 
              get answers about your community.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t py-6 md:py-0">
        <div className="container flex flex-col items-center justify-between gap-4 md:h-24 md:flex-row">
          <p className="text-center text-sm leading-loose text-muted-foreground md:text-left">
            Built for the community. Data sourced from official public records.
          </p>
          <p className="text-center text-sm text-muted-foreground">
            © {new Date().getFullYear()} Civic Commons
          </p>
        </div>
      </footer>
    </div>
  );
}
