"use client";

import Link from "next/link";
import { useQueries } from "@tanstack/react-query";
import { FileText, Waves } from "lucide-react";

import { getMyLibrary, listMyFindings } from "@ramanhub/api-client";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

interface Row {
  key: string;
  href: string;
  icon: "spectrum" | "finding";
  text: string;
  sub: string;
  at: number;
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
 * "Recent activity" derived from real data — the requester's newest spectra
 * and findings, merged by timestamp. There is no per-event activity feed
 * endpoint, so this is the honest approximation.
 */
export function RecentActivity() {
  const [lib, findings] = useQueries({
    queries: [
      {
        queryKey: ["my-library", "activity"],
        queryFn: () => getMyLibrary({ limit: 20 }),
      },
      { queryKey: ["my-findings"], queryFn: () => listMyFindings() },
    ],
  });

  const loading = lib.isLoading || findings.isLoading;

  const rows: Row[] = [
    ...(lib.data ?? []).map((s) => ({
      key: `s-${s.id}`,
      href: `/spectra/${s.id}`,
      icon: "spectrum" as const,
      text:
        s.state === "published"
          ? `Published ${s.title ?? "a spectrum"}`
          : `Uploaded ${s.title ?? "a spectrum"}`,
      sub:
        [s.material_type, s.modality].filter(Boolean).join(" · ") || "spectrum",
      // Not `published_at`: drafts don't have one, and filtering them out
      // here made the "Uploaded …" branch above unreachable.
      at: new Date(s.published_at ?? s.created_at).getTime() || 0,
    })),
    ...(findings.data ?? []).map((f) => ({
      key: `f-${f.id}`,
      href: `/findings/${f.id}`,
      icon: "finding" as const,
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
  ]
    .filter((r) => r.at > 0)
    .sort((a, b) => b.at - a.at)
    .slice(0, 6);

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="border-border border-b px-5 py-3.5 text-sm font-semibold">
        Recent activity
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
          {rows.map((r) => (
            <Link
              key={r.key}
              href={r.href}
              className="hover:bg-secondary/30 flex items-start gap-3 px-5 py-3 transition-colors"
            >
              <span className="bg-secondary text-muted-foreground mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full">
                {r.icon === "spectrum" ? (
                  <Waves className="size-3.5" aria-hidden />
                ) : (
                  <FileText className="size-3.5" aria-hidden />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-xs leading-snug font-medium">{r.text}</div>
                <div className="text-muted-foreground mt-0.5 truncate text-[10px]">
                  {r.sub}
                </div>
              </div>
              <span className="text-muted-foreground shrink-0 text-[10px]">
                {timeAgo(new Date(r.at).toISOString())}
              </span>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}
