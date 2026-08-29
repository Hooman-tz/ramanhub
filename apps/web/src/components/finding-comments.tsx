"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getSession,
  isApiError,
  listFindingComments,
  postFindingComment,
} from "@ramanhub/api-client";
import type { FindingComment } from "@ramanhub/api-client";

import { Button } from "@ramanhub/ui/button";

function timeAgo(iso: string): string {
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${Math.max(1, secs)}s`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.round(hrs / 24)}d`;
}

export function FindingComments({
  id,
  initial,
}: {
  id: string;
  initial?: FindingComment[];
}) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });
  const signedIn = !!session.data && !session.data.is_guest;

  const comments = useQuery({
    queryKey: ["finding-comments", id],
    queryFn: () => listFindingComments(id),
    initialData: initial,
  });

  const mutation = useMutation({
    mutationFn: () => postFindingComment(id, { body: body.trim() }),
    onSuccess: () => {
      setBody("");
      setError(null);
      void qc.invalidateQueries({ queryKey: ["finding-comments", id] });
    },
    onError: (e) =>
      setError(isApiError(e) ? e.message : "Could not post — try again."),
  });

  const list = comments.data ?? [];

  return (
    <section className="mt-8">
      <h2 className="text-sm font-semibold">
        Comments{list.length > 0 && ` (${list.length})`}
      </h2>

      <ul className="mt-3 space-y-3">
        {list.map((c) => (
          <li
            key={c.id}
            className="border-border rounded-lg border p-3 text-sm"
          >
            <div className="text-muted-foreground mb-1 flex items-center gap-2 text-xs">
              {c.author_handle ? (
                <a
                  href={`/u/${c.author_handle}`}
                  className="hover:text-foreground font-medium"
                >
                  {c.author_display_name ?? `@${c.author_handle}`}
                </a>
              ) : (
                <span className="font-medium">
                  {c.author_display_name ?? "Someone"}
                </span>
              )}
              <span>· {timeAgo(c.created_at)}</span>
            </div>
            <p className="whitespace-pre-wrap">{c.body}</p>
          </li>
        ))}
        {list.length === 0 && !comments.isLoading && (
          <li className="text-muted-foreground text-sm">
            No comments yet.
          </li>
        )}
      </ul>

      {signedIn ? (
        <form
          className="mt-4 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (body.trim()) mutation.mutate();
          }}
        >
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Add a comment…"
            rows={3}
            className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
          />
          {error && <p className="text-destructive text-xs">{error}</p>}
          <div className="flex justify-end">
            <Button
              type="submit"
              size="sm"
              disabled={!body.trim() || mutation.isPending}
            >
              {mutation.isPending ? "Posting…" : "Comment"}
            </Button>
          </div>
        </form>
      ) : (
        <p className="text-muted-foreground mt-4 text-sm">
          <a href="/login" className="hover:text-foreground underline">
            Sign in
          </a>{" "}
          to join the discussion.
        </p>
      )}
    </section>
  );
}
