"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";

import type { Dataset } from "@ramanhub/api-client";
import { listDatasetContributors, listDatasets } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Badge } from "@ramanhub/ui/badge";
import { Card } from "@ramanhub/ui/card";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { projectColor, ProjectSymbol } from "~/components/project-identity";
import { UserChip } from "~/components/user-chip";

function countLabel(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Who contributed to one project. Fetched only when the row is opened, so the
 * Office does not fire one request per project on load.
 */
function Contributors({ dataset }: { dataset: Dataset }) {
  const contributors = useQuery({
    queryKey: ["dataset-contributors", dataset.id],
    queryFn: () => listDatasetContributors(dataset.id),
  });

  if (contributors.isLoading) {
    return (
      <div className="space-y-2 px-5 pb-3 pl-14">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-7 w-40" />
      </div>
    );
  }

  if (contributors.isError) {
    return (
      <p className="text-muted-foreground px-5 pb-3 pl-14 text-[11px]">
        Could not load contributors.
      </p>
    );
  }

  const rows = contributors.data ?? [];

  return (
    <div className="space-y-0.5 px-5 pb-3 pl-14">
      {rows.map((person) => {
        const parts = [];
        if (person.spectra > 0)
          parts.push(countLabel(person.spectra, "spectrum", "spectra"));
        if (person.findings > 0)
          parts.push(countLabel(person.findings, "finding", "findings"));
        return (
          <UserChip
            key={person.user_id}
            person={person}
            className="-mx-1.5 px-1.5 py-1"
            meta={parts.join(" · ") || "no contributions yet"}
            badge={
              person.is_owner ? (
                <Badge variant="outline" className="px-1 py-0 text-[9px]">
                  owner
                </Badge>
              ) : null
            }
          />
        );
      })}
      {rows.length <= 1 ? (
        <p className="text-muted-foreground pt-1 text-[10px]">
          Add someone else&apos;s published spectrum to this project, or credit
          a co-author on a write-up, and they will appear here.
        </p>
      ) : null}
    </div>
  );
}

/**
 * The Office's project board: one row per `AnalysisDataset` — the entity the
 * API calls a "project folder" — carrying the owner-chosen colour and symbol
 * that identify it everywhere else in the app.
 *
 * Expanding a row shows everyone credited inside it. Contribution is derived
 * from data that already exists (a folder may hold anyone's published spectra,
 * and Findings carry co-authors), so this needs no invitations or membership
 * management to be useful.
 */
export function ProjectBoard() {
  const datasets = useQuery({
    queryKey: ["datasets"],
    queryFn: () => listDatasets(),
  });
  const [openId, setOpenId] = useState<string | null>(null);

  const rows = datasets.data ?? [];

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="border-border flex items-center justify-between border-b px-5 py-3.5">
        <div className="text-sm font-semibold">Projects</div>
        <Link
          href="/lab"
          className="text-primary text-[11px] font-medium hover:underline"
        >
          Manage in Data Lab →
        </Link>
      </div>

      {datasets.isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : datasets.isError ? (
        <p className="text-muted-foreground p-5 text-sm">
          Could not load your projects.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground p-5 text-sm">
          No projects yet.{" "}
          <Link href="/lab" className="text-primary hover:underline">
            Start one in the Data Lab
          </Link>
          .
        </p>
      ) : (
        <div className="divide-border divide-y">
          {rows.map((dataset) => {
            const color = projectColor(dataset.color);
            const open = openId === dataset.id;
            return (
              <div key={dataset.id}>
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setOpenId(open ? null : dataset.id)}
                  className="hover:bg-secondary/30 flex w-full items-center gap-3 px-5 py-3 text-left transition-colors"
                >
                  <span
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-md",
                      color.tint,
                      color.text,
                    )}
                  >
                    <ProjectSymbol icon={dataset.icon} className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {dataset.name}
                    </span>
                    <span className="text-muted-foreground mt-0.5 block text-[10px]">
                      {countLabel(
                        dataset.spectra.length,
                        "spectrum",
                        "spectra",
                      )}
                      {dataset.accession ? ` · ${dataset.accession}` : ""}
                    </span>
                  </span>
                  <Badge
                    variant={
                      dataset.state === "published" ? "success" : "outline"
                    }
                    className="shrink-0"
                  >
                    {dataset.state}
                  </Badge>
                  <ChevronRight
                    className={cn(
                      "text-muted-foreground size-4 shrink-0 transition-transform",
                      open && "rotate-90",
                    )}
                    aria-hidden
                  />
                </button>
                {open ? <Contributors dataset={dataset} /> : null}
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
