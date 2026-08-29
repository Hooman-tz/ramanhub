"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { isApiError, postNote, type SessionUser } from "@ramanhub/api-client";

import { Button } from "@ramanhub/ui/button";

export function Composer({ session }: { session: SessionUser | null }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      postNote({
        title: title.trim(),
        abstract_md: body.trim() || undefined,
        tags: tags
          .split(/[,\s]+/)
          .map((t) => t.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      setTitle("");
      setBody("");
      setTags("");
      setOpen(false);
      setError(null);
      void qc.invalidateQueries({ queryKey: ["feed"] });
    },
    onError: (e) =>
      setError(isApiError(e) ? e.message : "Could not post — try again."),
  });

  if (!session || session.is_guest) {
    return (
      <div className="border-border bg-card rounded-xl border p-4 text-sm">
        <p className="text-muted-foreground">
          Sign in to post a note to the feed.
        </p>
        <a href="/api/auth/login" className="mt-2 inline-block">
          <Button size="sm">Sign in with Google</Button>
        </a>
      </div>
    );
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="border-border bg-card text-muted-foreground hover:border-primary/40 w-full rounded-xl border p-4 text-left text-sm transition-colors"
      >
        Share a note, a result, a question…
      </button>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (title.trim()) mutation.mutate();
      }}
      className="border-border bg-card space-y-2 rounded-xl border p-4"
    >
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
        required
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Say more (markdown, optional)"
        rows={3}
        className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
      />
      <input
        value={tags}
        onChange={(e) => setTags(e.target.value)}
        placeholder="tags, comma separated (optional)"
        className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
      />
      {error && <p className="text-destructive text-xs">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setOpen(false)}
        >
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={!title.trim() || mutation.isPending}>
          {mutation.isPending ? "Posting…" : "Post"}
        </Button>
      </div>
    </form>
  );
}
