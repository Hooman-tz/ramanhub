"use client";

import { usePathname } from "next/navigation";

import { cn } from "@ramanhub/ui";

import { MobileNav } from "./mobile-nav";
import { Nav } from "./nav";
import { zoneForPath } from "./zone";

/**
 * App chrome: sticky glass nav, the per-section background wash, and the
 * mobile bottom nav. Pages still render their own `<main>` — this only
 * provides the tinted wrapper so we don't nest landmarks.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const zone = zoneForPath(pathname);

  return (
    <>
      <Nav />
      <div
        className={cn(
          "main-mobile-safe min-h-[calc(100vh-3.5rem)] transition-colors duration-300 motion-reduce:transition-none md:pb-0",
          zone.wash,
        )}
      >
        {children}
      </div>
      <MobileNav />
    </>
  );
}
