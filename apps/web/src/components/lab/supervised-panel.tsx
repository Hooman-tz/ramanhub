"use client";

import Link from "next/link";
import { Brain } from "lucide-react";

import { Card } from "@ramanhub/ui/card";

/**
 * Supervised modelling — classification and regression against labelled
 * spectra.
 *
 * Not built yet, and this says so plainly rather than showing controls that
 * would fail. What it is waiting on is not the model code: it is labels. The
 * platform has no notion of a training target today — `Spectrum` carries
 * `material_type` and free-form `confirmed_metadata`, neither of which is a
 * curated class label with a known vocabulary, and there is nowhere to record
 * a measured property to regress against.
 *
 * Shipping a classifier over `material_type` strings would produce a model
 * whose accuracy is really a measure of how consistently people typed, which
 * is worse than having nothing.
 */
export function SupervisedPanel() {
  return (
    <Card className="gap-4 p-6">
      <div className="flex items-center gap-2">
        <Brain className="text-muted-foreground size-4" aria-hidden />
        <h2 className="text-sm font-semibold">Supervised modelling</h2>
        <span className="border-border bg-muted text-muted-foreground rounded-full border px-2 py-0.5 text-[10px]">
          Not available yet
        </span>
      </div>

      <p className="text-foreground/80 text-sm leading-relaxed">
        Classification and regression need labelled spectra, and the platform
        has nowhere to put a label yet. A spectrum carries a free-text{" "}
        <span className="font-mono text-xs">material_type</span> and whatever
        the parser found — useful for search, but not a curated class
        vocabulary, and there is no field for a measured property to regress
        against.
      </p>

      <p className="text-foreground/80 text-sm leading-relaxed">
        Training on the free-text field would score how consistently people
        typed rather than what the spectra show, so it is deliberately not
        offered.
      </p>

      <div className="border-border bg-secondary/40 space-y-2 rounded-xl border p-4">
        <h3 className="text-muted-foreground text-xs font-semibold tracking-wider uppercase">
          What this needs first
        </h3>
        <ul className="text-foreground/80 list-disc space-y-1 pl-4 text-sm">
          <li>
            A label field on dataset membership, so the same spectrum can be
            labelled differently in two studies.
          </li>
          <li>
            A controlled vocabulary per dataset, so classes are comparable
            rather than typed twice.
          </li>
          <li>Numeric target values for regression, with units recorded.</li>
          <li>
            Held-out validation in the run record — an accuracy number without a
            stated split isn&apos;t evidence.
          </li>
        </ul>
      </div>

      <p className="text-muted-foreground text-sm">
        In the meantime,{" "}
        <Link
          href="/lab?mode=unsupervised"
          className="text-primary hover:underline"
        >
          unsupervised analysis
        </Link>{" "}
        will show you whether your groups separate at all — which is worth
        knowing before training anything on them.
      </p>
    </Card>
  );
}
