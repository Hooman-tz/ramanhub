"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Users, X } from "lucide-react";

import type { FollowUser } from "@ramanhub/api-client";
import { listFollowers, listFollowing } from "@ramanhub/api-client";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import { Combobox } from "@ramanhub/ui/combobox";
import { Label } from "@ramanhub/ui/label";

/**
 * Credit co-authors, suggesting from the people you actually work with.
 *
 * Suggestions come from your own follow graph rather than a global user
 * search. Two reasons: the person you're crediting is almost always someone
 * you already follow or who follows you, so a short relevant list beats a long
 * one; and it keeps this field off the global people search, which answers a
 * different question. That search exists now (`/v1/search/suggest`), but it is
 * not a directory: it returns only profiles their owners chose to publish, it
 * caps results, and it has no offset to page through. The constraint here was
 * always "no enumerable user list", and it still holds.
 *
 * Free typing still works. Someone you haven't followed can be credited by
 * handle — the server validates it and names the handle back if it's wrong, so
 * a typo fails loudly instead of silently crediting nobody.
 */

const MAX_SUGGESTIONS = 6;

function initials(name: string | null, handle: string | null): string {
  const source = name?.trim() ?? handle ?? "";
  if (!source) return "?";
  const [first = "", second = ""] = source.split(/\s+/).filter(Boolean);
  return (second ? first.slice(0, 1) + second.slice(0, 1) : source)
    .slice(0, 2)
    .toUpperCase();
}

export function CoAuthorField({
  handles,
  onChange,
  /** The composing user's own handle — the follow graph is read from it. */
  viewerHandle,
}: {
  handles: string[];
  onChange: (next: string[]) => void;
  viewerHandle: string | null;
}) {
  const [draft, setDraft] = useState("");

  const network = useQuery({
    queryKey: ["co-author-network", viewerHandle],
    queryFn: async () => {
      if (!viewerHandle) return [] as FollowUser[];
      // Both directions: a collaborator may follow you without the reverse.
      const [following, followers] = await Promise.all([
        listFollowing(viewerHandle).catch(() => [] as FollowUser[]),
        listFollowers(viewerHandle).catch(() => [] as FollowUser[]),
      ]);
      // People you chose to follow rank first, then dedupe by id.
      const seen = new Set<string>();
      return [...following, ...followers].filter((u) => {
        if (seen.has(u.id) || !u.handle) return false;
        seen.add(u.id);
        return true;
      });
    },
    enabled: !!viewerHandle,
    staleTime: 5 * 60 * 1000,
  });

  const query = draft.trim().replace(/^@/, "").toLowerCase();
  const chosen = useMemo(
    () => new Set(handles.map((h) => h.toLowerCase())),
    [handles],
  );

  const suggestions = useMemo(() => {
    const pool = (network.data ?? []).filter(
      (u) => !chosen.has(u.handle.toLowerCase()),
    );
    if (!query) return pool.slice(0, MAX_SUGGESTIONS);
    return pool
      .filter(
        (u) =>
          u.handle.toLowerCase().includes(query) ||
          (u.display_name ?? "").toLowerCase().includes(query),
      )
      .slice(0, MAX_SUGGESTIONS);
  }, [network.data, chosen, query]);

  const add = (handle: string) => {
    const clean = handle.trim().replace(/^@/, "");
    if (!clean) return;
    if (!chosen.has(clean.toLowerCase())) onChange([...handles, clean]);
    setDraft("");
  };

  return (
    <div className="space-y-1">
      <Label htmlFor="composer-coauthors" className="text-xs">
        <Users className="mr-1 inline size-3.5" aria-hidden />
        Co-authors
      </Label>

      <Combobox
        items={suggestions}
        value={draft}
        onValueChange={setDraft}
        onSelect={(user) => add(user.handle)}
        onSubmitRaw={(raw) => add(raw)}
        listboxId="composer-coauthor-suggestions"
        inputProps={{
          id: "composer-coauthors",
          placeholder: handles.length ? "" : "@handle or name",
          className: "min-w-28 flex-1 bg-transparent py-0.5 text-sm focus:outline-none",
          onKeyDownCapture: (e) => {
            if (e.key === "Backspace" && !draft && handles.length) {
              onChange(handles.slice(0, -1));
            }
            // A comma commits too, the way every tag field does.
            if (e.key === ",") {
              e.preventDefault();
              add(draft);
            }
          },
        }}
        renderItem={(user) => (
          <span className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm">
            <Avatar className="size-6">
              {user.avatar_url ? <AvatarImage src={user.avatar_url} alt="" /> : null}
              <AvatarFallback className="text-[10px]">
                {initials(user.display_name, user.handle)}
              </AvatarFallback>
            </Avatar>
            <span className="min-w-0 flex-1">
              <span className="block truncate">{user.display_name ?? user.handle}</span>
              <span className="text-muted-foreground block truncate text-xs">
                @{user.handle}
                {user.affiliation ? ` · ${user.affiliation}` : ""}
              </span>
            </span>
          </span>
        )}
      >
        {(input) => (
          <div className="border-input bg-background focus-within:border-ring flex flex-wrap items-center gap-1.5 rounded-md border px-2 py-1.5">
            {handles.map((handle) => (
              <span
                key={handle}
                className="bg-muted inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
              >
                @{handle}
                <button
                  type="button"
                  aria-label={`Remove @${handle}`}
                  onClick={() => onChange(handles.filter((h) => h !== handle))}
                  className="text-muted-foreground hover:text-foreground cursor-pointer"
                >
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            ))}
            {input}
          </div>
        )}
      </Combobox>

      <p className="text-foreground/60 text-xs">
        {network.data && network.data.length > 0
          ? "Suggested from people you follow. Anyone with an account can be credited by handle."
          : "Handles of people with an account here — they'll link to their profiles."}
      </p>
    </div>
  );
}
