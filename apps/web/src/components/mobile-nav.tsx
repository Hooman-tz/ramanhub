"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Search } from "lucide-react";

import { cn } from "@ramanhub/ui";

import { openCommandPalette } from "./search/command-palette";
import { NAV_LINKS, zoneForPath } from "./zone";

/**
 * iOS-style liquid-glass bottom navigation, shown below `md`.
 * Mirrors the desktop pill nav in `nav.tsx`.
 */
export function MobileNav() {
  const pathname = usePathname();
  const zone = zoneForPath(pathname);

  return (
    <nav className="glass-bottom-nav fixed inset-x-0 bottom-0 z-40 md:hidden">
      <div className="flex items-stretch justify-around">
        {NAV_LINKS.map(({ href, label, icon: Icon, isActive }) => {
          const active = isActive(pathname);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex h-14 flex-1 flex-col items-center justify-center gap-1 transition-colors active:scale-95 motion-reduce:transition-none motion-reduce:active:scale-100",
                active ? zone.accentText : "text-muted-foreground",
              )}
            >
              <Icon className="size-5" aria-hidden />
              <span className="text-[10px] font-semibold tracking-tight">
                {label}
              </span>
            </Link>
          );
        })}

        {/* There is no keyboard here, so search needs somewhere to be tapped. */}
        <button
          type="button"
          onClick={openCommandPalette}
          className="text-muted-foreground flex h-14 flex-1 flex-col items-center justify-center gap-1 transition-colors active:scale-95 motion-reduce:transition-none motion-reduce:active:scale-100"
        >
          <Search className="size-5" aria-hidden />
          <span className="text-[10px] font-semibold tracking-tight">Search</span>
        </button>
      </div>
    </nav>
  );
}
