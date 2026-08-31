"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getSession, logout } from "@ramanhub/api-client";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@ramanhub/ui/dropdown-menu";

function initials(name: string | null, email: string | null): string {
  const source = name?.trim() ?? email?.trim() ?? "";
  if (!source) return "?";
  const [first = "", second = ""] = source.split(/\s+/).filter(Boolean);
  const letters = second ? first.slice(0, 1) + second.slice(0, 1) : source;
  return letters.slice(0, 2).toUpperCase();
}

export function Nav() {
  const router = useRouter();
  const qc = useQueryClient();

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
    <header className="border-border bg-background/80 sticky top-0 z-40 w-full border-b backdrop-blur">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <Link href="/" className="text-lg font-medium tracking-tight">
          Spectra<span className="font-bold">Insight</span>
        </Link>

        {isFullUser ? (
          <DropdownMenu>
            <DropdownMenuTrigger className="focus-visible:ring-ring/50 rounded-full outline-none focus-visible:ring-[3px]">
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
        ) : (
          <Link
            href="/login"
            className="text-muted-foreground hover:text-foreground text-sm font-medium transition-colors"
          >
            Sign in
          </Link>
        )}
      </div>
    </header>
  );
}
