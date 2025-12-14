import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
});

export const metadata: Metadata = {
  title: {
    default: 'Civic Commons',
    template: '%s | Civic Commons',
  },
  description: 'Your community information assistant. Find local events, meeting minutes, and civic documents.',
  keywords: ['civic', 'community', 'local government', 'events', 'meetings', 'documents'],
  authors: [{ name: 'Civic Commons' }],
  openGraph: {
    type: 'website',
    locale: 'en_US',
    siteName: 'Civic Commons',
  },
  robots: {
    index: true,
    follow: true,
  },
};

interface RootLayoutProps {
  children: React.ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans antialiased`}>
        <div className="relative flex min-h-screen flex-col">
          <main className="flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}
