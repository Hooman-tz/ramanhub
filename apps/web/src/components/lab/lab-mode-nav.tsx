"use client";

import type { LucideIcon } from "lucide-react";
import { Boxes, Brain, Network, SlidersHorizontal } from "lucide-react";

import { cn } from "@ramanhub/ui";

/**
 * What the Data Lab is doing right now.
 *
 * The lab owns everything data: the database itself, and the analysis run
 * over it. The office is for paperwork — activity, messages, project status —
 * so nothing here duplicates it.
 */
export type LabMode = "database" | "prep" | "unsupervised" | "supervised";

export const LAB_MODES: LabMode[] = [
  "database",
  "prep",
  "unsupervised",
  "supervised",
];

/** Narrow an untrusted `?mode=` value; anything unknown falls back to the home tab. */
export function parseLabMode(value: string | null): LabMode {
  return LAB_MODES.includes(value as LabMode) ? (value as LabMode) : "database";
}

const TABS: {
  mode: LabMode;
  label: string;
  icon: LucideIcon;
  hint: string;
  /** Starts the "Analysis" half of the bar. */
  startsGroup?: boolean;
}[] = [
  {
    mode: "database",
    label: "Database",
    icon: Boxes,
    hint: "Datasets and spectra",
  },
  {
    mode: "prep",
    label: "Prep",
    icon: SlidersHorizontal,
    hint: "Processing toolbox",
    startsGroup: true,
  },
  {
    mode: "unsupervised",
    label: "Unsupervised",
    icon: Network,
    hint: "PCA and clustering",
  },
  {
    mode: "supervised",
    label: "Supervised",
    icon: Brain,
    hint: "Classification and regression",
  },
];

export function LabModeNav({
  mode,
  onSelect,
}: {
  mode: LabMode;
  onSelect: (mode: LabMode) => void;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-1 rounded-lg border p-1"
      role="tablist"
      aria-label="Data Lab section"
    >
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const active = tab.mode === mode;
        return (
          <div key={tab.mode} className="contents">
            {/* A divider, not a separate control: everything to its right is
                analysis over whatever the database half has selected. */}
            {tab.startsGroup && (
              <span className="bg-border mx-1 h-6 w-px" aria-hidden />
            )}
            <button
              type="button"
              role="tab"
              aria-selected={active}
              title={tab.hint}
              onClick={() => onSelect(tab.mode)}
              className={cn(
                "flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors duration-150 outline-none",
                "focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none",
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" aria-hidden />
              {tab.label}
            </button>
          </div>
        );
      })}
    </div>
  );
}
