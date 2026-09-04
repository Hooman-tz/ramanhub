import type { LucideIcon } from "lucide-react";
import { createElement } from "react";
import {
  Atom,
  Beaker,
  Dna,
  FlaskConical,
  Folder,
  Hexagon,
  Layers,
  Microscope,
} from "lucide-react";

/**
 * A project's visual identity: one of eight colours and one of eight symbols,
 * chosen by its owner and stored on the dataset.
 *
 * Mirrors `PROJECT_COLORS` / `PROJECT_ICONS` in
 * `backend/app/routers/analysis.py`, which is the source of truth. The lookups
 * below fall back to slot 0 rather than throwing, so a server that has grown a
 * ninth slot degrades to a sane default here instead of blanking a row — the
 * two lists do not have to ship together.
 *
 * Every class string is written out in full. Tailwind v4 scans source for
 * literal class names, so a computed `bg-project-${color}` would never be
 * generated and the swatch would silently render transparent.
 */
export const PROJECT_COLORS = [
  "teal",
  "amber",
  "blue",
  "violet",
  "rose",
  "green",
  "cyan",
  "slate",
] as const;

export type ProjectColor = (typeof PROJECT_COLORS)[number];

export interface ProjectColorClasses {
  /** Solid fill — dots, and the icon chip behind a white glyph. */
  solid: string;
  /** Foreground use — an icon or label drawn in the project's colour. */
  text: string;
  /** Soft background tint, for the chip behind a coloured glyph. */
  tint: string;
  /** Ring used to mark the selected swatch in the picker. */
  ring: string;
}

const COLOR_CLASSES: Record<ProjectColor, ProjectColorClasses> = {
  teal: {
    solid: "bg-project-teal",
    text: "text-project-teal",
    tint: "bg-project-teal/10",
    ring: "ring-project-teal",
  },
  amber: {
    solid: "bg-project-amber",
    text: "text-project-amber",
    tint: "bg-project-amber/10",
    ring: "ring-project-amber",
  },
  blue: {
    solid: "bg-project-blue",
    text: "text-project-blue",
    tint: "bg-project-blue/10",
    ring: "ring-project-blue",
  },
  violet: {
    solid: "bg-project-violet",
    text: "text-project-violet",
    tint: "bg-project-violet/10",
    ring: "ring-project-violet",
  },
  rose: {
    solid: "bg-project-rose",
    text: "text-project-rose",
    tint: "bg-project-rose/10",
    ring: "ring-project-rose",
  },
  green: {
    solid: "bg-project-green",
    text: "text-project-green",
    tint: "bg-project-green/10",
    ring: "ring-project-green",
  },
  cyan: {
    solid: "bg-project-cyan",
    text: "text-project-cyan",
    tint: "bg-project-cyan/10",
    ring: "ring-project-cyan",
  },
  slate: {
    solid: "bg-project-slate",
    text: "text-project-slate",
    tint: "bg-project-slate/10",
    ring: "ring-project-slate",
  },
};

/** Human-readable colour names, for `aria-label` on the picker swatches. */
export const COLOR_LABELS: Record<ProjectColor, string> = {
  teal: "Teal",
  amber: "Amber",
  blue: "Blue",
  violet: "Violet",
  rose: "Rose",
  green: "Green",
  cyan: "Cyan",
  slate: "Slate",
};

export const PROJECT_ICONS = [
  "folder",
  "flask",
  "atom",
  "microscope",
  "beaker",
  "dna",
  "layers",
  "hexagon",
] as const;

export type ProjectIcon = (typeof PROJECT_ICONS)[number];

const ICON_COMPONENTS: Record<ProjectIcon, LucideIcon> = {
  folder: Folder,
  flask: FlaskConical,
  atom: Atom,
  microscope: Microscope,
  beaker: Beaker,
  dna: Dna,
  layers: Layers,
  hexagon: Hexagon,
};

/** Human-readable symbol names, for `aria-label` on the picker buttons. */
export const ICON_LABELS: Record<ProjectIcon, string> = {
  folder: "Folder",
  flask: "Flask",
  atom: "Atom",
  microscope: "Microscope",
  beaker: "Beaker",
  dna: "DNA",
  layers: "Layers",
  hexagon: "Hexagon",
};

function isColor(value: string): value is ProjectColor {
  return (PROJECT_COLORS as readonly string[]).includes(value);
}

function isIcon(value: string): value is ProjectIcon {
  return (PROJECT_ICONS as readonly string[]).includes(value);
}

/** Class set for a stored colour value, defaulting to the first slot. */
export function projectColor(
  value: string | null | undefined,
): ProjectColorClasses {
  return COLOR_CLASSES[value && isColor(value) ? value : PROJECT_COLORS[0]];
}

/** Icon component for a stored symbol value, defaulting to the first slot. */
export function projectIcon(value: string | null | undefined): LucideIcon {
  return ICON_COMPONENTS[value && isIcon(value) ? value : PROJECT_ICONS[0]];
}

/**
 * Renders a project's symbol.
 *
 * Exists so callers never bind the looked-up icon to a local of their own:
 * `react-hooks/static-components` reads `const Foo = projectIcon(x)` followed
 * by `<Foo />` as a component defined during render, even though
 * `ICON_COMPONENTS` is module-level and the reference is stable. Going through
 * `createElement` here keeps the lookup out of JSX position, and makes this
 * the single path project identity renders through.
 */
export function ProjectSymbol({
  icon,
  className,
}: {
  icon: string | null | undefined;
  className?: string;
}) {
  return createElement(projectIcon(icon), { className, "aria-hidden": true });
}
