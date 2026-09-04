import type { LucideIcon } from "lucide-react";
import {
  FileText,
  FolderPlus,
  PenLine,
  UploadCloud,
  Waves,
} from "lucide-react";

/**
 * The kinds of thing that show up in the Office's activity list.
 *
 * These are synthesised on the client from the library, findings and dataset
 * queries — there is no per-event feed endpoint, so this is the honest set of
 * events the existing data can support. The names are `noun.verb` so the list
 * reads the same as the backend's own vocabulary if one is ever added.
 *
 * Each kind carries a distinct *symbol* as well as a distinct colour. Colour is
 * never the sole carrier: the row still parses in greyscale, and for a reader
 * who cannot distinguish teal from green.
 */
export type ActivityKind =
  | "spectrum.published"
  | "spectrum.uploaded"
  | "finding.published"
  | "finding.drafted"
  | "dataset.created";

export interface ActivityKindStyle {
  /** Short label for the legend. */
  label: string;
  icon: LucideIcon;
  /** Foreground colour for the glyph. */
  text: string;
  /** Soft chip behind the glyph. */
  tint: string;
  /** Solid swatch, used by the legend. */
  solid: string;
}

/**
 * Reuses the existing semantic tokens rather than adding new ones: they are
 * already tuned for both themes, so dark mode comes out right for free.
 */
export const ACTIVITY_KINDS: Record<ActivityKind, ActivityKindStyle> = {
  "spectrum.published": {
    label: "Spectrum published",
    icon: Waves,
    text: "text-success",
    tint: "bg-success/10",
    solid: "bg-success",
  },
  "spectrum.uploaded": {
    label: "Spectrum uploaded",
    icon: UploadCloud,
    text: "text-chart-3",
    tint: "bg-chart-3/10",
    solid: "bg-chart-3",
  },
  "finding.published": {
    label: "Finding published",
    icon: FileText,
    text: "text-primary",
    tint: "bg-primary/10",
    solid: "bg-primary",
  },
  "finding.drafted": {
    label: "Finding drafted",
    icon: PenLine,
    text: "text-accent",
    tint: "bg-accent/10",
    solid: "bg-accent",
  },
  "dataset.created": {
    label: "Project created",
    icon: FolderPlus,
    text: "text-chart-5",
    tint: "bg-chart-5/10",
    solid: "bg-chart-5",
  },
};

/** Legend order — published work first, then drafts, then containers. */
export const ACTIVITY_LEGEND: ActivityKind[] = [
  "spectrum.published",
  "finding.published",
  "spectrum.uploaded",
  "finding.drafted",
  "dataset.created",
];
