"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQueries } from "@tanstack/react-query";

import {
  getMyLibrary,
  listDatasets,
  listMyFindings,
} from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

import type { ActivityKind } from "./activity-kinds";
import { projectColor } from "~/components/project-identity";
import { ACTIVITY_KINDS, ACTIVITY_LEGEND } from "./activity-kinds";

interface ProjectTag {
  id: string;
  name: string;
  color: string;
}

interface Row {
  key: string;
  href: string;
  kind: ActivityKind;
  text: string;
  sub: string;
  at: number;
  project?: ProjectTag;
}

function timeAgo(iso: string): string {
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  const steps: [number, string][] = [
    [60, "s"],
    [60, "m"],
    [24, "h"],
    [30, "d"],
    [12, "mo"],
    [Number.POSITIVE_INFINITY, "y"],
  ];
  let v = secs;
  for (const [d, label] of steps) {
    if (v < d) return `${Math.max(1, Math.floor(v))}${label} ago`;
    v /= d;
  }
  return "";
}

/**
 * "Recent activity" derived from real data — the requester's newest spectra,
 * findings and projects, merged by timestamp. There is no per-event activity
 * feed endpoint, so this is the honest approximation.
 *
 * Every row is colour-coded and symbol-coded by kind (see `activity-kinds.ts`),
 * because the four spectrum/finding events previously rendered in one identical
 * grey chip: you could not tell "published to the commons" from "saved a draft"
 * without reading the sentence.
 *
 * The datasets query earns its keep three times over: it supplies the
 * `dataset.created` rows, the spectrum -> project index used for the row tag,
 * and each project's colour.
 */
export function RecentActivity() {
  const [lib, findings, datasets] = useQueries({
    queries: [
      {
        queryKey: ["my-library", "activity"],
        queryFn: () => getMyLibrary({ limit: 20 }),
      },
      { queryKey: ["my-findings"], queryFn: () => listMyFindings() },
      { queryKey: ["datasets"], queryFn: () => listDatasets() },
    ],
  });

  const loading = lib.isLoading || findings.isLoading || datasets.isLoading;

  /** spectrum id -> the project it sits in. First membership wins. */
  const projectOf = useMemo(() => {
    const index = new Map<string, ProjectTag>();
    for (const dataset of datasets.data ?? []) {
      const tag = { id: dataset.id, name: dataset.name, color: dataset.color };
      for (const spectrum of dataset.spectra) {
        if (!index.has(spectrum.id)) index.set(spectrum.id, tag);
      }
    }
    return index;
  }, [datasets.data]);

  const rows: Row[] = [
    ...(lib.data ?? []).map((s) => ({
      key: `s-${s.id}`,
      href: `/spectra/${s.id}`,
      kind: (s.state === "published"
        ? "spectrum.published"
        : "spectrum.uploaded") as ActivityKind,
      text:
        s.state === "published"
          ? `Published ${s.title ?? "a spectrum"}`
          : `Uploaded ${s.title ?? "a spectrum"}`,
      sub:
        [s.material_type, s.modality].filter(Boolean).join(" · ") || "spectrum",
      // Not `published_at`: drafts don't have one, and filtering them out
      // here made the "Uploaded …" branch above unreachable.
      at: new Date(s.published_at ?? s.created_at).getTime() || 0,
      project: projectOf.get(s.id),
    })),
    ...(findings.data ?? []).map((f) => ({
      key: `f-${f.id}`,
      href: `/findings/${f.id}`,
      kind: (f.state === "published"
        ? "finding.published"
        : "finding.drafted") as ActivityKind,
      text:
        f.state === "published"
          ? `Published "${f.title}"`
          : `Started a draft: "${f.title}"`,
      sub:
        (f.tags ?? [])
          .slice(0, 3)
          .map((t) => `#${t}`)
          .join(" ") || "finding",
      at: new Date(f.published_at ?? f.updated_at).getTime() || 0,
    })),
    ...(datasets.data ?? []).map((d) => ({
      key: `d-${d.id}`,
      href: `/lab?dataset=${d.id}`,
      kind: "dataset.created" as ActivityKind,
      text: `Started the project "${d.name}"`,
      sub: `${d.spectra.length} spectr${d.spectra.length === 1 ? "um" : "a"}`,
      at: new Date(d.created_at ?? 0).getTime() || 0,
      project: { id: d.id, name: d.name, color: d.color },
    })),
  ]
    .filter((r) => r.at > 0)
    .sort((a, b) => b.at - a.at)
    .slice(0, 8);

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="border-border border-b px-5 py-3.5 text-sm font-semibold">
        Recent activity
      </div>

      {/* The encoding has to be legible without a key elsewhere on the page. */}
      <div className="border-border text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-5 py-2 text-[10px]">
        {ACTIVITY_LEGEND.map((kind) => (
          <span key={kind} className="flex items-center gap-1">
            <span
              className={cn(
                "size-1.5 rounded-full",
                ACTIVITY_KINDS[kind].solid,
              )}
              aria-hidden
            />
            {ACTIVITY_KINDS[kind].label}
          </span>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground p-5 text-sm">Nothing yet.</p>
      ) : (
        <div className="divide-border divide-y">
          {rows.map((r) => {
            const style = ACTIVITY_KINDS[r.kind];
            const Icon = style.icon;
            return (
              <Link
                key={r.key}
                href={r.href}
                className="hover:bg-secondary/30 flex items-start gap-3 px-5 py-3 transition-colors"
              >
                <span
                  className={cn(
                    "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full",
                    style.tint,
                    style.text,
                  )}
                >
                  <Icon className="size-3.5" aria-hidden />
                  <span className="sr-only">{style.label}</span>
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-xs leading-snug font-medium">
                    {r.text}
                  </div>
                  <div className="text-muted-foreground mt-0.5 flex items-center gap-1.5 truncate text-[10px]">
                    {r.project ? (
                      <>
                        <span
                          className={cn(
                            "size-1.5 shrink-0 rounded-full",
                            projectColor(r.project.color).solid,
                          )}
                          aria-hidden
                        />
                        <span className="truncate">{r.project.name}</span>
                        <span aria-hidden>·</span>
                      </>
                    ) : null}
                    <span className="truncate">{r.sub}</span>
                  </div>
                </div>
                <span className="text-muted-foreground shrink-0 text-[10px]">
                  {timeAgo(new Date(r.at).toISOString())}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </Card>
  );
}
