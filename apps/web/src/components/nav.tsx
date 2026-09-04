"use client";

import { Suspense } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { logout } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import { Button } from "@ramanhub/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ramanhub/ui/dropdown-menu";

import { useSession } from "~/hooks/use-session";
import { NavAction } from "./nav-action";
import { WaveMark } from "./wave-mark";
import { openCommandPalette } from "./search/command-palette";
import { NAV_LINKS, zoneForPath } from "./zone";

function initials(name: string | null, email: string | null): string {
  const source = name?.trim() ?? email?.trim() ?? "";
  if (!source) return "?";
  const [first = "", second = ""] = source.split(/\s+/).filter(Boolean);
  const letters = second ? first.slice(0, 1) + second.slice(0, 1) : source;
  return letters.slice(0, 2).toUpperCase();
}

export function Nav() {
  const pathname = usePathname();
  const qc = useQueryClient();

  const zone = zoneForPath(pathname);

  const { user, isFullUser, isKnownSignedOut } = useSession();

  const signOut = useMutation({
    mutationFn: () => logout(),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["session"] });
      // Hard navigation for the same reason as the guest path in `login/page.tsx`:
      // the cached `/` payload is the *feed*, so `router.push` would leave a
      // just-signed-out user looking at it.
      window.location.assign("/");
    },
  });


  return (
    <header className="glass-nav sticky top-0 z-40 w-full">
      <div className="mx-auto flex h-14 max-w-5xl items-center gap-4 px-4">
        <Link
          href="/"
          aria-label="Spectra Insight — home"
          className="focus-visible:ring-ring/50 -mx-1 flex items-center gap-2 rounded-md px-1 py-1 focus-visible:ring-[3px] focus-visible:outline-none"
        >
          <span
            className={cn(
              "flex size-7 items-center justify-center rounded-lg text-white shadow-sm",
              zone.accentBg,
            )}
          >
            <WaveMark className="size-3.5" />
          </span>
          <span className="text-sm font-bold tracking-tight">
            Spectra<span className={zone.accentText}>Insight</span>
          </span>
        </Link>

        {/* Desktop pill nav */}
        <nav className="border-border/70 bg-card/60 ml-2 hidden items-center gap-1 rounded-2xl border p-1 shadow-sm backdrop-blur md:flex">
          {NAV_LINKS.filter(
            ({ gated }) => !gated || !isKnownSignedOut,
          ).map(({ href, label, icon: Icon, isActive }) => {
            const active = isActive(pathname);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-xl px-4 py-1.5 text-sm font-semibold transition-colors motion-reduce:transition-none",
                  active
                    ? cn(zone.accentBg, "text-white shadow-sm")
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex min-w-0 flex-1 items-center justify-end gap-1">
          {/* The primary action depends on the route — search on the feed, a
              new dataset in the lab, a new post elsewhere. It reads the URL,
              so it needs a Suspense boundary to keep pages statically
              renderable. */}
          <Suspense fallback={null}>
            <NavAction isFullUser={isFullUser} />
          </Suspense>

          {/* ⌘K is invisible to anyone who hasn't been told about it. */}
          <button
            type="button"
            onClick={openCommandPalette}
            aria-label="Search"
            className="border-border/70 bg-card/60 text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex shrink-0 items-center gap-1.5 rounded-xl border px-2 py-1.5 transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
          >
            <Search className="size-4" aria-hidden />
            <kbd className="hidden font-sans text-[11px] md:inline">⌘K</kbd>
          </button>

          {/* `&& user` is what narrows `user` for the avatar block below —
              `isFullUser` is a plain boolean and carries no type information. */}
          {isFullUser && user ? (
            <>
              <DropdownMenu>
                <DropdownMenuTrigger
                  aria-label="Account menu"
                  className="focus-visible:ring-ring/50 hover:bg-muted flex cursor-pointer items-center justify-center rounded-full p-1.5 transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
                >
                  <Avatar>
                    {user.avatar_url ? (
                      <AvatarImage
                        src={user.avatar_url}
                        alt={user.display_name ?? "Account"}
                      />
                    ) : null}
                    <AvatarFallback>
                      {initials(user.display_name, user.email)}
                    </AvatarFallback>
                  </Avatar>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-44">
                  <DropdownMenuItem asChild>
                    <Link href="/office">Office</Link>
                  </DropdownMenuItem>
                  {user.profile_handle ? (
                    <DropdownMenuItem asChild>
                      <Link href={`/u/${user.profile_handle}`}>My profile</Link>
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem asChild>
                    <Link href="/settings">Settings</Link>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    disabled={signOut.isPending}
                    onSelect={(e) => {
                      e.preventDefault();
                      signOut.mutate();
                    }}
                  >
                    Sign out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="text-foreground/80 hover:text-foreground hover:bg-muted focus-visible:ring-ring/50 hidden min-h-9 items-center rounded-md px-3 text-sm font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none sm:inline-flex"
              >
                Sign in
              </Link>
              <Button asChild size="sm">
                <Link href="/login">Get started</Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
