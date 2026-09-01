"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getSession, logout } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ramanhub/ui/dropdown-menu";

import { ComposeFab } from "./compose-fab";
import { NAV_LINKS, zoneForPath } from "./zone";

function initials(name: string | null, email: string | null): string {
  const source = name?.trim() ?? email?.trim() ?? "";
  if (!source) return "?";
  const [first = "", second = ""] = source.split(/\s+/).filter(Boolean);
  const letters = second ? first.slice(0, 1) + second.slice(0, 1) : source;
  return letters.slice(0, 2).toUpperCase();
}

/** The spectrum waveform mark used in the logo lockup. */
function WaveMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 14 14" fill="none" className={className} aria-hidden>
      <polyline
        points="0,10 2,10 3,7 4,9 5,5 6,8 7,4 8,6 9,8 10,4 11,7 12,6 14,10"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Nav() {
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();

  const zone = zoneForPath(pathname);

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });

  const signOut = useMutation({
    mutationFn: () => logout(),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["session"] });
      router.push("/");
    },
  });

  const user = session.data;
  const isFullUser = !!user && !user.is_guest;

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
          {NAV_LINKS.map(({ href, label, icon: Icon, isActive }) => {
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

        <div className="ml-auto flex items-center gap-1">
          {isFullUser ? (
            <>
              <ComposeFab variant="nav-button" />
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
            <Link
              href="/login"
              className="text-foreground/80 hover:text-foreground hover:bg-muted focus-visible:ring-ring/50 inline-flex min-h-9 items-center rounded-md px-3 text-sm font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
            >
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
