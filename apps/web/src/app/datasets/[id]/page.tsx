import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Database } from "lucide-react";

import { getDataset, isApiError } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Badge } from "@ramanhub/ui/badge";
import { Card } from "@ramanhub/ui/card";

import { BackLink } from "~/components/back-link";
import { DatasetExploreButton } from "~/components/dataset-explore-button";
import { ForkDataButton } from "~/components/fork-data-button";
import { projectColor, ProjectSymbol } from "~/components/project-identity";
import { ProvenanceTrail } from "~/components/provenance-trail";
import { serverApiOpts } from "~/lib/server-api";

export const dynamic = "force-dynamic";

/**
 * A published dataset — the citable home of the data behind a post.
 *
 * The API returns 404 (never 403) for a dataset the viewer can't read, so a
 * private folder and a nonexistent id are indistinguishable here by design.
 */
export default async function DatasetPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const opts = await serverApiOpts();

  let dataset;
  try {
    dataset = await getDataset(id, opts);
  } catch (e) {
    if (isApiError(e) && e.status >= 400 && e.status < 500) notFound();
    throw e;
  }

  const members = dataset.spectra;
  const excitations = [
    ...new Set(
      members
        .map((s) => s.excitation_wavelength_nm)
        .filter((v): v is number => v != null),
    ),
  ];

  const facts: [string, string][] = [
    ["Spectra", String(members.length)],
    ["Modality", dataset.modality],
    ...(excitations.length > 0
      ? ([["Excitation", excitations.map((v) => `${v} nm`).join(", ")]] as [
          string,
          string,
        ][])
      : []),
    ...(dataset.license_id
      ? ([["License", dataset.license_id]] as [string, string][])
      : []),
  ];

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <BackLink />

      {/* Dataset-level lineage: this folder is a fork of another one. The
          per-spectrum trail at the foot covers the finer-grained case. */}
      {dataset.parent_dataset_id && (
        <nav
          aria-label="Dataset provenance"
          className="border-border bg-secondary/40 mt-3 flex flex-wrap items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs"
        >
          <Database className="text-muted-foreground size-3.5" aria-hidden />
          <span className="text-muted-foreground">Forked from</span>
          <Link
            href={`/datasets/${dataset.parent_dataset_id}`}
            className="text-primary hover:underline"
          >
            the original dataset
          </Link>
        </nav>
      )}

      <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-foreground/80 flex flex-wrap items-center gap-2 text-xs">
            {dataset.owner_handle && (
              <Link
                href={`/u/${dataset.owner_handle}`}
                className="hover:text-foreground font-medium"
              >
                @{dataset.owner_handle}
              </Link>
            )}
            {dataset.accession && (
              <span className="font-mono">· {dataset.accession}</span>
            )}
          </div>
          <h1 className="mt-1 flex items-center gap-2 text-2xl font-bold tracking-tight">
            {/* The same symbol and colour the owner sees in their Office, so a
                project stays recognisable wherever it is linked from. */}
            <ProjectSymbol
              icon={dataset.icon}
              className={cn(
                "size-5 shrink-0",
                projectColor(dataset.color).text,
              )}
            />
            {dataset.name}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge
              variant={dataset.state === "published" ? "default" : "secondary"}
            >
              {dataset.state}
            </Badge>
            {dataset.doi && (
              <a
                href={`https://doi.org/${dataset.doi}`}
                className="text-primary text-xs hover:underline"
              >
                {dataset.doi}
              </a>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {members.length > 0 && (
            <>
              <DatasetExploreButton
                name={dataset.name}
                spectra={members.map((s) => ({
                  spectrum_id: s.id,
                  label: s.title ?? s.accession,
                }))}
              />
              <ForkDataButton source="dataset" id={dataset.id} size="sm" />
            </>
          )}
        </div>
      </div>

      {dataset.description && (
        <p className="text-foreground/80 mt-3 text-sm leading-relaxed">
          {dataset.description}
        </p>
      )}

      {facts.length > 0 && (
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {facts.map(([label, value]) => (
            <div
              key={label}
              className="border-border bg-secondary/40 rounded-xl border p-3"
            >
              <div className="text-muted-foreground text-xs">{label}</div>
              <div className="mt-0.5 text-sm font-medium">{value}</div>
            </div>
          ))}
        </div>
      )}

      <section className="mt-6" aria-labelledby="dataset-spectra-heading">
        <h2
          id="dataset-spectra-heading"
          className="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase"
        >
          Spectra
        </h2>
        {members.length === 0 ? (
          <p className="text-foreground/70 rounded-xl border border-dashed p-6 text-center text-sm">
            This dataset has no spectra yet.
          </p>
        ) : (
          <Card className="gap-0 overflow-hidden p-0">
            <ul className="divide-border divide-y">
              {members.map((s) => (
                <li key={s.id} className="flex items-center gap-2 px-3 py-2">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">
                      {s.title ?? "Untitled spectrum"}
                    </span>
                    <span className="text-muted-foreground font-mono text-xs">
                      {s.accession ?? s.id.slice(0, 8)}
                      <span className="ml-1.5 font-sans">· {s.state}</span>
                      {s.excitation_wavelength_nm != null && (
                        <span className="ml-1.5">
                          · {s.excitation_wavelength_nm} nm
                        </span>
                      )}
                    </span>
                  </span>
                  <Link
                    href={`/spectra/${s.id}`}
                    aria-label={`Open ${s.title ?? "this spectrum"}`}
                    className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex size-9 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
                  >
                    <ArrowRight className="size-4" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>

      {members[0] && <ProvenanceTrail spectrumId={members[0].id} />}
    </main>
  );
}
