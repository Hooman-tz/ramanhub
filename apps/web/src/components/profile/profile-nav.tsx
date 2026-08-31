"use client";

import type { LucideIcon } from "lucide-react";

import { cn } from "@ramanhub/ui";

export interface NavSection {
  id: string;
  label: string;
  icon: LucideIcon;
}

/**
 * Left rail for the profile shell. Sticky vertical list on `md+`, a
 * horizontally-scrolling strip below that. The active item carries
 * `aria-current="page"`.
 */
export function ProfileNav({
  sections,
  active,
  onSelect,
}: {
  sections: NavSection[];
  active: string;
  onSelect: (id: string) => void;
}) {
  return (
    <nav aria-label="Profile sections" className="md:w-[220px] md:shrink-0">
      <ul className="flex gap-1 overflow-x-auto pb-1 md:sticky md:top-20 md:flex-col md:overflow-visible md:pb-0">
        {sections.map((s) => {
          const isActive = s.id === active;
          const Icon = s.icon;
          return (
            <li key={s.id} className="shrink-0">
              <button
                type="button"
                aria-current={isActive ? "page" : undefined}
                onClick={() => onSelect(s.id)}
                className={cn(
                  "flex min-h-11 w-auto cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors duration-150 outline-none md:w-full",
                  "focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-foreground/70 hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                {s.label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
