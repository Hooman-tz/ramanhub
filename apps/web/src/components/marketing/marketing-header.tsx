import Link from "next/link";

import { Button } from "@ramanhub/ui/button";

import { WaveMark } from "~/components/wave-mark";

/**
 * The landing page's own header. Deliberately not the app `<Nav />`: that one
 * links to Office and Lab, which bounce a signed-out visitor straight to
 * `/login`, and it fires a session query on mount. This stays a static server
 * component with nothing but links.
 */
export function MarketingHeader() {
  return (
    <header className="glass-nav sticky top-0 z-40 w-full">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-4 px-4">
        <Link
          href="/"
          aria-label="Spectra Insight — home"
          className="focus-visible:ring-ring/50 flex items-center gap-2 rounded font-bold tracking-tight focus-visible:ring-[3px] focus-visible:outline-none"
        >
          <span className="bg-primary text-primary-foreground flex size-6 items-center justify-center rounded-md">
            <WaveMark className="size-3.5" />
          </span>
          <span>
            Spectra<span className="text-primary">Insight</span>
          </span>
        </Link>

        <nav className="ml-auto hidden items-center gap-1 sm:flex">
          <a
            href="#problem"
            className="text-foreground/70 hover:text-foreground focus-visible:ring-ring/50 rounded px-3 py-1.5 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
          >
            Why
          </a>
          <a
            href="#capabilities"
            className="text-foreground/70 hover:text-foreground focus-visible:ring-ring/50 rounded px-3 py-1.5 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
          >
            What you can do
          </a>
          <Link
            href="/library"
            className="text-foreground/70 hover:text-foreground focus-visible:ring-ring/50 rounded px-3 py-1.5 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
          >
            Library
          </Link>
        </nav>

        <div className="ml-auto flex items-center gap-2 sm:ml-0">
          <Link
            href="/login"
            className="text-foreground/70 hover:text-foreground focus-visible:ring-ring/50 hidden rounded px-3 py-1.5 text-sm focus-visible:ring-[3px] focus-visible:outline-none sm:inline-flex"
          >
            Sign in
          </Link>
          <Button asChild size="sm">
            <Link href="/login">Get started</Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
