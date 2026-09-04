import Link from "next/link";

import { WaveMark } from "~/components/wave-mark";

const LINKS = [
  { href: "/library", label: "Library" },
  { href: "/about", label: "About" },
  { href: "/terms", label: "Terms" },
  { href: "/privacy", label: "Privacy" },
];

/** The app has no footer; this one belongs to the marketing section only. */
export function MarketingFooter() {
  return (
    <footer className="border-border mt-20 border-t">
      <div className="mx-auto flex max-w-5xl flex-col gap-4 px-4 py-8 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <span className="bg-primary text-primary-foreground flex size-5 items-center justify-center rounded">
            <WaveMark className="size-3" />
          </span>
          <span className="text-sm font-semibold tracking-tight">
            Spectra Insight
          </span>
          <span className="text-muted-foreground text-xs">
            Spectra in sight. Spectral insight.
          </span>
        </div>

        <nav className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded text-sm focus-visible:ring-[3px] focus-visible:outline-none"
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}
