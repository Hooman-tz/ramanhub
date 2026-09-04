"use client";

import { cn } from "@ramanhub/ui";
import { Label } from "@ramanhub/ui/label";

import type { ProjectColor, ProjectIcon } from "./project-identity";
import {
  COLOR_LABELS,
  ICON_LABELS,
  PROJECT_COLORS,
  PROJECT_ICONS,
  projectColor,
  projectIcon,
} from "./project-identity";

/**
 * Colour and symbol pickers for a project.
 *
 * Both rows are plain `<button>`s in document order, so they are reachable and
 * operable by keyboard with the app's normal focus ring; each carries an
 * `aria-label` naming the colour or symbol, since a grid that communicates only
 * through colour is unusable with a screen reader.
 *
 * `null` is a real state and means "let the server choose" — on create, the API
 * assigns the next free palette slot, so an unset picker is not an error.
 */
export function ProjectIdentityPicker({
  color,
  icon,
  onColorChange,
  onIconChange,
  hint,
}: {
  color: ProjectColor | null;
  icon: ProjectIcon | null;
  onColorChange: (color: ProjectColor) => void;
  onIconChange: (icon: ProjectIcon) => void;
  hint?: string;
}) {
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>Colour</Label>
        <div className="flex flex-wrap gap-1.5">
          {PROJECT_COLORS.map((value) => (
            <button
              key={value}
              type="button"
              aria-label={COLOR_LABELS[value]}
              aria-pressed={color === value}
              onClick={() => onColorChange(value)}
              className={cn(
                "focus-visible:ring-ring/50 size-6 rounded-full outline-none focus-visible:ring-[3px]",
                projectColor(value).solid,
                color === value &&
                  cn(
                    "ring-offset-background ring-2 ring-offset-2",
                    projectColor(value).ring,
                  ),
              )}
            />
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <Label>Symbol</Label>
        <div className="flex flex-wrap gap-1.5">
          {PROJECT_ICONS.map((value) => {
            const Icon = projectIcon(value);
            const active = icon === value;
            return (
              <button
                key={value}
                type="button"
                aria-label={ICON_LABELS[value]}
                aria-pressed={active}
                onClick={() => onIconChange(value)}
                className={cn(
                  "focus-visible:ring-ring/50 flex size-7 items-center justify-center rounded-md border transition-colors outline-none focus-visible:ring-[3px]",
                  active
                    ? cn(
                        "border-transparent",
                        projectColor(color).tint,
                        projectColor(color).text,
                      )
                    : "border-border text-muted-foreground hover:bg-secondary",
                )}
              >
                <Icon className="size-3.5" aria-hidden />
              </button>
            );
          })}
        </div>
      </div>

      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
  );
}
