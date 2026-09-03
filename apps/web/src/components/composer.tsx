"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ImageIcon, LineChart, Plus } from "lucide-react";

import type { SessionUser } from "@ramanhub/api-client";
import { createFinding, isApiError, postNote } from "@ramanhub/api-client";
import { Avatar, AvatarFallback, AvatarImage } from "@ramanhub/ui/avatar";
import { Button } from "@ramanhub/ui/button";

/**
 * `dialog`   — bare form, no card chrome; used inside the compose dialog
 *              (FAB / nav "+"). Renders the form directly (no click-to-expand).
 * `expanded` — the feed's inline composer. Collapsed to a single line until
 *              the "+" is pressed: the feed is for reading, and a three-field
 *              form sitting permanently above it pushed the actual posts down
 *              for everyone who wasn't writing one. Once open it has a card,
 *              avatar header, tag helper, and a secondary row that spins up a
 *              real Finding draft so "post with visuals" leads to the gallery
 *              editor.
 */
export type ComposerVariant = "dialog" | "expanded";

function initials(name: string | null): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function Composer({
  session,
  variant = "dialog",
  onPosted,
}: {
  session: SessionUser | null;
  variant?: ComposerVariant;
  /** Called after a successful note post (e.g. to close the dialog). */
  onPosted?: () => void;
}) {
  const qc = useQueryClient();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [error, setError] = useState<string | null>(null);
  /** Only meaningful for `expanded`; the dialog variant is already open. */
  const [open, setOpen] = useState(false);

  const parseTags = () =>
    tags
      .split(/[,\s]+/)
      .map((t) => t.trim())
      .filter(Boolean);

  const post = useMutation({
    mutationFn: () =>
      postNote({
        title: title.trim(),
        abstract_md: body.trim() || undefined,
        tags: parseTags(),
      }),
    onSuccess: () => {
      setTitle("");
      setBody("");
      setTags("");
      setError(null);
      void qc.invalidateQueries({ queryKey: ["feed"] });
      onPosted?.();
    },
    onError: (e) =>
      setError(isApiError(e) ? e.message : "Could not post — try again."),
  });

  const draft = useMutation({
    mutationFn: () => createFinding({ title: title.trim(), tags: parseTags() }),
    onSuccess: (finding) => {
      setError(null);
      router.push(`/findings/${finding.id}`);
    },
    onError: (e) =>
      setError(
        isApiError(e) ? e.message : "Could not start a draft — try again.",
      ),
  });

  if (!session || session.is_guest) {
    return (
      <div className="border-border bg-card rounded-xl border p-4 text-sm shadow-sm">
        <p className="text-foreground/80">
          Sign in to post a note to the feed.
        </p>
        <Button asChild size="sm" className="mt-2">
          <a href="/login">Sign in</a>
        </Button>
      </div>
    );
  }

  const hasTitle = !!title.trim();
  const busy = post.isPending || draft.isPending;
  const expanded = variant === "expanded";

  if (expanded && !open) {
    return (
      <div className="border-border bg-card flex items-center gap-3 rounded-xl border p-3 shadow-sm">
        <Avatar>
          {session.avatar_url ? (
            <AvatarImage
              src={session.avatar_url}
              alt={session.display_name ?? "You"}
            />
          ) : null}
          <AvatarFallback>{initials(session.display_name)}</AvatarFallback>
        </Avatar>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 min-w-0 flex-1 cursor-pointer rounded-md px-1 py-1.5 text-left text-sm transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
        >
          Share a note or a finding…
        </button>
        <Button
          type="button"
          size="icon"
          aria-label="Write a post"
          onClick={() => setOpen(true)}
        >
          <Plus className="size-4" aria-hidden />
        </Button>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (hasTitle) post.mutate();
      }}
      className={
        expanded
          ? "border-border bg-card space-y-3 rounded-xl border p-4 shadow-sm"
          : "space-y-2"
      }
    >
      {expanded && (
        <div className="flex items-center gap-3">
          <Avatar>
            {session.avatar_url ? (
              <AvatarImage
                src={session.avatar_url}
                alt={session.display_name ?? "You"}
              />
            ) : null}
            <AvatarFallback>{initials(session.display_name)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <p className="text-sm font-semibold tracking-tight">
              Share with the community
            </p>
            <p className="text-foreground/60 text-xs">
              Post a note, or start a finding with visuals.
            </p>
          </div>
        </div>
      )}

      <label htmlFor="composer-title" className="sr-only">
        Title
      </label>
      <input
        id="composer-title"
        autoFocus={variant === "dialog"}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
        required
      />
      <label htmlFor="composer-body" className="sr-only">
        Body
      </label>
      <textarea
        id="composer-body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Say more (markdown, optional)"
        rows={3}
        className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm leading-relaxed focus-visible:ring-[3px] focus-visible:outline-none"
      />
      <div className="space-y-1">
        <label htmlFor="composer-tags" className="sr-only">
          Tags
        </label>
        <input
          id="composer-tags"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="tags, comma separated (optional)"
          className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm focus-visible:ring-[3px] focus-visible:outline-none"
        />
        {expanded && (
          <p className="text-foreground/60 text-xs">
            Add up to 5 tags, comma separated
          </p>
        )}
      </div>

      {error && (
        <p className="text-destructive text-xs" role="alert">
          {error}
        </p>
      )}

      {expanded ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!hasTitle || busy}
            onClick={() => draft.mutate()}
          >
            <LineChart aria-hidden />
            Attach spectra
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!hasTitle || busy}
            onClick={() => draft.mutate()}
          >
            <ImageIcon aria-hidden />
            Attach figure
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="ml-auto"
            disabled={busy}
            onClick={() => {
              setOpen(false);
              setError(null);
            }}
          >
            Cancel
          </Button>
          <Button type="submit" size="sm" disabled={!hasTitle || busy}>
            {post.isPending ? "Posting…" : "Post"}
          </Button>
        </div>
      ) : (
        <div className="flex justify-end gap-2">
          <Button type="submit" size="sm" disabled={!hasTitle || busy}>
            {post.isPending ? "Posting…" : "Post"}
          </Button>
        </div>
      )}
    </form>
  );
}
