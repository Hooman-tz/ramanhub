import type { LucideIcon } from "lucide-react";
import { FlaskConical, Home, Newspaper } from "lucide-react";

/**
 * Per-section theming ported from the Figma design system's `ZONES` map.
 * Each route family gets a background wash (`.zone-*` in styles.css) and an
 * accent colour (`--zone-*` tokens) that fills the active nav pill.
 */
export type ZoneKey = "home" | "discover" | "mylab" | "viewer";

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
const VIEWER: Zone = {
  key: "viewer",
  wash: "zone-viewer",
  accentBg: "bg-zone-viewer",
  accentText: "text-zone-viewer",
};

export function zoneForPath(pathname: string): Zone {
  if (pathname.startsWith("/office")) return HOME;
  if (pathname.startsWith("/lab") || pathname.startsWith("/upload"))
    return MYLAB;
  if (pathname.startsWith("/spectra")) return VIEWER;
  return DISCOVER;
}

export interface NavLink {
  href: string;
  label: string;
  icon: LucideIcon;
  isActive: (pathname: string) => boolean;
}

export const NAV_LINKS: NavLink[] = [
  {
    href: "/office",
    label: "Office",
    icon: Home,
    isActive: (p) => p.startsWith("/office"),
  },
  {
    href: "/",
    label: "Feed",
    icon: Newspaper,
    isActive: (p) =>
      p === "/" || p.startsWith("/findings") || p.startsWith("/spectra"),
  },
  {
    href: "/lab",
    label: "Lab",
    icon: FlaskConical,
    isActive: (p) => p.startsWith("/lab") || p.startsWith("/upload"),
  },
];
