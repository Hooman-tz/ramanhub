import Link from "next/link";

import { cn } from "@ramanhub/ui";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";

/**
 * Warm accents for an avatar with no image. Ported from the feed card, which
 * is where this deterministic-colour-per-person idea started; kept here so the
 * same person reads the same colour wherever they appear.
 */
const AVATAR_PALETTE = [
  "#0d6b6e",
  "#b45309",
  "#1e3a5f",
  "#6d28d9",
  "#44403c",
] as const;

/** Deterministic warm accent for an author avatar, keyed off their id/handle. */
export function avatarAccent(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length] ?? AVATAR_PALETTE[0];
}

/** Up to two initials, falling back to the handle and then to "?". */
export function initials(
  name: string | null | undefined,
  handle?: string | null,
): string {
  const source = name ?? handle;
  if (!source) return "?";
  return (
    source
      .split(/\s+/)
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase() || "?"
  );
}

export interface UserChipPerson {
  handle: string | null;
  display_name: string | null;
  avatar_url?: string | null;
}

/**
 * Avatar + name + `@handle`, linking to the profile when there is a handle to
 * link to. `meta` is the caller's own summary line — contribution counts, an
 * affiliation, a role — rendered under the handle.
 */
export function UserChip({
  person,
  meta,
  badge,
  className,
}: {
  person: UserChipPerson;
  meta?: string;
  badge?: React.ReactNode;
  className?: string;
}) {
  const name = person.display_name ?? person.handle ?? "Unknown";
  const seed = person.handle ?? name;

  const body = (
    <>
      <Avatar className="size-7 shrink-0">
        {person.avatar_url ? (
          <AvatarImage src={person.avatar_url} alt="" />
        ) : null}
        <AvatarFallback
          className="text-[10px] font-semibold text-white"
          style={{ backgroundColor: avatarAccent(seed) }}
        >
          {initials(person.display_name, person.handle)}
        </AvatarFallback>
      </Avatar>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-xs font-medium">{name}</span>
          {badge}
        </span>
        <span className="text-muted-foreground block truncate text-[10px]">
          {person.handle ? `@${person.handle}` : "no handle"}
          {meta ? ` · ${meta}` : ""}
        </span>
      </span>
    </>
  );

  if (!person.handle) {
    return (
      <span className={cn("flex items-center gap-2", className)}>{body}</span>
    );
  }

  return (
    <Link
      href={`/u/${person.handle}`}
      className={cn(
        "hover:bg-secondary/40 flex items-center gap-2 rounded-md transition-colors",
        className,
      )}
    >
      {body}
    </Link>
  );
}
