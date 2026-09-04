"use client";

import { useMemo } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, Flag } from "lucide-react";

import type {
  LibraryMatchResult,
  LibraryUnmixResult,
  ReferenceEntry,
} from "@ramanhub/api-client";
import { reportReference } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Badge } from "@ramanhub/ui/badge";
import { Card } from "@ramanhub/ui/card";

import { SpectrumChart } from "~/components/charts/spectrum-chart";

/**
 * The presentational half of the reference library, shared by the two places
 * it surfaces: the standalone `/library` page and the Data Lab's Library tab.
 *
 * Kept in one module deliberately. These read-outs make claims about a user's
 * data — a similarity score, a composition — and two drifting copies would
 * eventually disagree about how confident to look.
 */

export function TrustBadge({ tier }: { tier: ReferenceEntry["trust_tier"] }) {
  const curated = tier === "curated";
  return (
    <Badge
      variant={curated ? "secondary" : "outline"}
      title={
        curated
          ? "Bundled or staff-vetted reference data."
          : "User-contributed: matchable immediately, but not vetted."
      }
      className="shrink-0"
    >
      {curated ? "Curated" : "Community"}
    </Badge>
  );
}

/** How confident a similarity score should look at a glance. */
function scoreTone(similarity: number) {
  if (similarity >= 0.95) return "text-emerald-600 dark:text-emerald-400";
  if (similarity >= 0.85) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
}

function ReportButton({ referenceId }: { referenceId: string }) {
  const report = useMutation({
    mutationFn: () =>
      reportReference(referenceId, { reason: "Flagged from the library" }),
  });
  return (
    <button
      type="button"
      title={
        report.isSuccess
          ? "Reported for review"
          : "Report this reference as mislabelled"
      }
      disabled={report.isPending || report.isSuccess}
      onClick={() => report.mutate()}
      className={cn(
        "text-muted-foreground hover:text-foreground shrink-0 cursor-pointer",
        report.isSuccess && "text-amber-500",
      )}
    >
      <Flag className="size-3.5" aria-hidden />
      <span className="sr-only">Report this reference</span>
    </button>
  );
}

export function MatchList({
  result,
  overlaid,
  onOverlay,
  picked,
  onTogglePick,
  showPicker,
}: {
  result: LibraryMatchResult;
  overlaid: string | null;
  onOverlay: (id: string) => void;
  picked: string[];
  onTogglePick: (id: string) => void;
  /** Show the component checkboxes — only meaningful once a mixture is in play. */
  showPicker: boolean;
}) {
  return (
    <ul className="divide-y">
      {result.matches.map((m) => {
        const isPicked = picked.includes(m.reference.id);
        return (
          <li key={m.reference.id} className="flex items-center gap-3 py-2">
            {showPicker && (
              <input
                type="checkbox"
                checked={isPicked}
                onChange={() => onTogglePick(m.reference.id)}
                aria-label={`Include ${m.reference.compound_name} as a component`}
                className="size-4 cursor-pointer"
              />
            )}
            <button
              type="button"
              onClick={() => onOverlay(m.reference.id)}
              aria-pressed={overlaid === m.reference.id}
              title="Draw this reference over your spectrum"
              className={cn(
                "min-w-0 flex-1 cursor-pointer rounded px-1 py-0.5 text-left",
                overlaid === m.reference.id && "bg-muted",
              )}
            >
              <p className="truncate text-sm font-medium">
                {m.reference.compound_name}
              </p>
              <p className="text-muted-foreground truncate text-xs">
                {m.matched_peak_count} of {result.query_peaks.length} bands
                matched
                {m.reference.chemical_formula
                  ? ` · ${m.reference.chemical_formula}`
                  : ""}
              </p>
            </button>
            <TrustBadge tier={m.reference.trust_tier} />
            <span
              className={cn(
                "w-11 text-right text-sm font-medium tabular-nums",
                scoreTone(m.similarity),
              )}
              title="Similarity to your spectrum"
            >
              {(m.similarity * 100).toFixed(0)}%
            </span>
            <ReportButton referenceId={m.reference.id} />
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Pick the compounds to fit, inside the step that fits them.
 *
 * Deliberately plainer than `MatchList`: no scores, no trust badges, no report
 * action. Those belong to the question "which of these is it?" — this control
 * answers the later, different question "which of these are in it?", and
 * repeating the ranking here would just invite re-reading it.
 */
export function ComponentChooser({
  result,
  picked,
  onToggle,
  max = 6,
}: {
  result: LibraryMatchResult;
  picked: string[];
  onToggle: (id: string) => void;
  max?: number;
}) {
  const atLimit = picked.length >= max;
  return (
    <ul className="flex flex-col gap-1">
      {result.matches.slice(0, 8).map((m) => {
        const isPicked = picked.includes(m.reference.id);
        const disabled = !isPicked && atLimit;
        return (
          <li key={m.reference.id}>
            <label
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                isPicked ? "bg-muted" : "hover:bg-muted/60",
                disabled && "cursor-not-allowed opacity-50",
              )}
            >
              <input
                type="checkbox"
                checked={isPicked}
                disabled={disabled}
                onChange={() => onToggle(m.reference.id)}
                className="size-4 cursor-pointer"
              />
              <span className="min-w-0 flex-1 truncate">
                {m.reference.compound_name}
              </span>
              {m.reference.chemical_formula && (
                <span className="text-muted-foreground shrink-0 text-xs">
                  {m.reference.chemical_formula}
                </span>
              )}
            </label>
          </li>
        );
      })}
    </ul>
  );
}

export function MixtureNotice({ result }: { result: LibraryMatchResult }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" aria-hidden />
      <p className="min-w-0 flex-1 text-xs">
        {result.mixture_reason ??
          "This may be a mixture of more than one compound."}
      </p>
    </div>
  );
}

export function UnmixReadout({ result }: { result: LibraryUnmixResult }) {
  const series = useMemo(
    () => [
      {
        name: "Yours",
        wavenumbers: result.grid_wavenumbers,
        intensities: result.observed,
      },
      {
        name: "Fitted mixture",
        wavenumbers: result.grid_wavenumbers,
        intensities: result.fitted,
      },
      {
        name: "Left over",
        wavenumbers: result.grid_wavenumbers,
        intensities: result.residual,
      },
    ],
    [result],
  );

  const poorFit = result.r_squared < 0.8;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-muted-foreground text-xs">
        Spectral weights — the share of your signal each reference accounts for.
        Not concentrations: Raman cross-sections differ between compounds, so
        this is not how much of the sample is each thing.
      </p>

      <ul className="flex flex-col gap-2">
        {result.components.map((c) => (
          <li key={c.reference.id} className="flex items-center gap-3">
            <span className="min-w-0 flex-1 truncate text-sm">
              {c.reference.compound_name}
            </span>
            <div className="bg-muted h-2 w-32 overflow-hidden rounded-full">
              <div
                className="bg-zone-library h-full"
                style={{ width: `${Math.round(c.weight * 100)}%` }}
              />
            </div>
            <span className="w-11 text-right text-sm font-medium tabular-nums">
              {(c.weight * 100).toFixed(0)}%
            </span>
          </li>
        ))}
      </ul>

      <p className="text-muted-foreground text-xs tabular-nums">
        Fit quality R² {result.r_squared.toFixed(3)} · unexplained{" "}
        {(result.residual_norm_fraction * 100).toFixed(1)}%
      </p>

      {(poorFit || result.collinear_warnings.length > 0) && (
        <div className="flex flex-col gap-1 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
          {poorFit && (
            <p className="text-xs">
              This fit explains little of your signal — treat the weights as
              unreliable rather than as a composition.
            </p>
          )}
          {result.collinear_warnings.map((w) => (
            <p key={w} className="text-xs">
              {w}
            </p>
          ))}
        </div>
      )}

      <div className="rounded-lg border p-2">
        <SpectrumChart
          mode="trace"
          height={240}
          series={series}
          display={{ showLegend: true }}
          ariaLabel="Your spectrum, the fitted mixture, and what is left over"
        />
      </div>
    </div>
  );
}

export function ReferenceRow({ row }: { row: ReferenceEntry }) {
  return (
    <li className="flex items-center gap-3 p-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{row.compound_name}</p>
        <p className="text-muted-foreground truncate text-xs">
          {[row.chemical_formula, row.source_id, row.source]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      <TrustBadge tier={row.trust_tier} />
      {row.provenance_url && (
        <a
          href={row.provenance_url}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground"
          aria-label={`Source record for ${row.compound_name}`}
        >
          <ExternalLink className="size-3.5" aria-hidden />
        </a>
      )}
    </li>
  );
}

export function EmptyCard({ icon: Icon, message }: { icon: React.ElementType; message: string }) {
  return (
    <Card className="p-8">
      <div className="flex flex-col items-center justify-center gap-2 text-center">
        <Icon className="text-muted-foreground size-8" aria-hidden />
        <p className="text-muted-foreground max-w-sm text-sm">{message}</p>
      </div>
    </Card>
  );
}
