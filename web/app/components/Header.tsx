'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const navItems = [
  { href: '/events', label: 'Events' },
  { href: '/videos', label: 'Videos' },
  { href: '/documents', label: 'Documents' },
  { href: '/legislation', label: 'Legislation' },
  { href: '/newsletters', label: 'Newsletters' },
  { href: '/discuss', label: 'Discuss' },
];

export function Header() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <div className="mr-4 flex">
          <Link href="/" className="mr-6 flex items-center space-x-2">
            <span className="font-bold text-xl">Civic Commons</span>
          </Link>
        </div>
        <nav className="flex items-center space-x-6 text-sm font-medium">
          {navItems.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`transition-colors hover:text-foreground/80 ${
                  isActive 
                    ? 'text-foreground font-semibold' 
                    : 'text-foreground/60'
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
