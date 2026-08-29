import Link from "next/link";
import { notFound } from "next/navigation";
import { getFinding, isApiError } from "@ramanhub/api-client";

import { serverApiOpts } from "~/lib/server-api";

export const dynamic = "force-dynamic";

export default async function FindingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let finding;
  try {
    finding = await getFinding(id, await serverApiOpts());
  } catch (e) {
    if (isApiError(e) && e.status === 404) notFound();
    throw e;
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <Link href="/" className="text-muted-foreground text-sm hover:underline">
        ← Feed
      </Link>

      <div className="text-muted-foreground mt-4 flex items-center gap-2 text-xs">
        {finding.owner_handle ? (
          <Link
            href={`/u/${finding.owner_handle}`}
            className="hover:text-foreground font-medium"
          >
            {finding.owner_display_name ?? finding.owner_handle}
          </Link>
        ) : (
          <span className="font-medium">
            {finding.owner_display_name ?? "Someone"}
          </span>
        )}
        {finding.accession && (
          <span className="font-mono">· {finding.accession}</span>
        )}
        <span
          className={
            finding.state === "published"
              ? "text-primary"
              : "text-muted-foreground"
          }
        >
          · {finding.state}
        </span>
      </div>

      <h1 className="mt-2 text-2xl font-bold tracking-tight">{finding.title}</h1>
      {finding.abstract_md && (
        <p className="text-foreground/90 mt-3 whitespace-pre-wrap text-sm">
          {finding.abstract_md}
        </p>
      )}

      {finding.tags && finding.tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
          {finding.tags.map((t) => (
            <span key={t} className="bg-muted rounded px-1.5 py-0.5">
              #{t}
            </span>
          ))}
        </div>
      )}

      <div className="text-muted-foreground mt-4 flex gap-4 text-xs">
        <span>▲ {finding.vote_count}</span>
        <span>💬 {finding.comment_count}</span>
        {finding.doi && (
          <a
            href={`https://doi.org/${finding.doi}`}
            className="text-primary hover:underline"
          >
            {finding.doi}
          </a>
        )}
      </div>

      {finding.spectra.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold">Spectra</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {finding.spectra.map((s) => (
              <li key={s.spectrum_id} className="text-muted-foreground">
                {s.label ?? s.title ?? s.accession ?? s.spectrum_id}
              </li>
            ))}
          </ul>
        </section>
      )}

      {finding.entries.length > 0 && (
        <section className="mt-6 space-y-4">
          <h2 className="text-sm font-semibold">Thread</h2>
          {finding.entries.map((entry) => (
            <div
              key={entry.id}
              className="border-border rounded-lg border p-3 text-sm"
            >
              <div className="text-muted-foreground mb-1 text-xs uppercase">
                {entry.kind}
              </div>
              {entry.body_md && (
                <p className="whitespace-pre-wrap">{entry.body_md}</p>
              )}
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
