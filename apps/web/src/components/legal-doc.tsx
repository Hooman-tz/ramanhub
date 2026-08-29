import Link from "next/link";

/**
 * Shared shell for the /terms and /privacy pages. Content is written to be
 * accurate to how the platform works today; it has not been reviewed by a
 * lawyer and must be before any non-beta launch.
 */
export function LegalDoc({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <Link href="/" className="text-muted-foreground text-sm hover:underline">
        ← Feed
      </Link>
      <h1 className="mt-4 text-2xl font-bold tracking-tight">{title}</h1>
      <p className="text-muted-foreground mt-1 text-xs">
        Last updated: {updated} · Draft for the early-access beta — not yet
        reviewed by a lawyer.
      </p>
      <div className="mt-6 space-y-6 text-sm leading-relaxed [&_h2]:mt-6 [&_h2]:text-sm [&_h2]:font-semibold [&_p]:text-foreground/90">
        {children}
      </div>
      <p className="text-muted-foreground mt-10 text-xs">
        Questions? <a className="hover:underline" href="mailto:hello@spectra-in.site">hello@spectra-in.site</a>
      </p>
    </main>
  );
}
