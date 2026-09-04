import type { LucideIcon } from "lucide-react";
import { FlaskConical, Home, Library, Newspaper } from "lucide-react";

/**
 * Per-section theming ported from the Figma design system's `ZONES` map.
 * Each route family gets a background wash (`.zone-*` in styles.css) and an
 * accent colour (`--zone-*` tokens) that fills the active nav pill.
 */
export type ZoneKey = "home" | "discover" | "mylab" | "library" | "viewer";

interface Zone {
  key: ZoneKey;
  /** class applied to the content wrapper — see styles.css */
  wash: string;
  /** Tailwind bg utility for the active pill / active mobile icon */
  accentBg: string;
  accentText: string;
}

const HOME: Zone = {
  key: "home",
  wash: "zone-home",
  accentBg: "bg-zone-home",
  accentText: "text-zone-home",
};
const DISCOVER: Zone = {
  key: "discover",
  wash: "zone-discover",
  accentBg: "bg-zone-discover",
  accentText: "text-zone-discover",
};
const MYLAB: Zone = {
  key: "mylab",
  wash: "zone-mylab",
  accentBg: "bg-zone-mylab",
  accentText: "text-zone-mylab",
};
const LIBRARY: Zone = {
  key: "library",
  wash: "zone-library",
  accentBg: "bg-zone-library",
  accentText: "text-zone-library",
};
const VIEWER: Zone = {
  key: "viewer",
  wash: "zone-viewer",
  accentBg: "bg-zone-viewer",
  accentText: "text-zone-viewer",
};

export function zoneForPath(pathname: string): Zone {
  if (pathname.startsWith("/office")) return HOME;
  if (pathname.startsWith("/library")) return LIBRARY;
  if (pathname.startsWith("/lab") || pathname.startsWith("/upload"))
    return MYLAB;
  if (pathname.startsWith("/spectra") || pathname.startsWith("/datasets"))
    return VIEWER;
  return DISCOVER;
}

export interface NavLink {
  href: string;
  label: string;
  icon: LucideIcon;
  isActive: (pathname: string) => boolean;
  /**
   * Bounces to `/login?next=…` without a full account, so it is dead weight for
   * a signed-out visitor. `/library` and the feed are deliberately not gated —
   * both read fine anonymously.
   */
  gated?: boolean;
}

export const NAV_LINKS: NavLink[] = [
  {
    href: "/office",
    label: "Office",
    icon: Home,
    isActive: (p) => p.startsWith("/office"),
    gated: true,
  },
  {
    href: "/",
    label: "Feed",
    icon: Newspaper,
    isActive: (p) =>
      p === "/" ||
      p.startsWith("/findings") ||
      p.startsWith("/spectra") ||
      p.startsWith("/datasets"),
  },
  {
    href: "/lab",
    label: "Lab",
    icon: FlaskConical,
    isActive: (p) => p.startsWith("/lab") || p.startsWith("/upload"),
    gated: true,
  },
  {
    href: "/library",
    label: "Library",
    icon: Library,
    isActive: (p) => p.startsWith("/library"),
  },
];
