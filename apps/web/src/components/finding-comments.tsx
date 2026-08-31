"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { FindingComment } from "@ramanhub/api-client";
import {
  getSession,
  isApiError,
  listFindingComments,
  postFindingComment,
} from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
import { Skeleton } from "@ramanhub/ui/skeleton";

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
    <section className="mt-10">
      <h2 className="text-base font-semibold tracking-tight">
        Comments{list.length > 0 && ` (${list.length})`}
      </h2>

      {comments.isLoading && list.length === 0 && (
        <div className="mt-4 space-y-3" aria-hidden>
          {[0, 1].map((i) => (
            <div key={i} className="border-border rounded-lg border p-3">
              <Skeleton className="h-3 w-40" />
              <Skeleton className="mt-2 h-4 w-full" />
              <Skeleton className="mt-1.5 h-4 w-2/3" />
            </div>
          ))}
        </div>
      )}

      <ul className="mt-4 space-y-3">
        {list.map((c) => (
          <li
            key={c.id}
            className="border-border rounded-lg border p-3.5 text-sm"
          >
            <div className="mb-1.5 flex items-center gap-2 text-xs">
              {c.author_handle ? (
                <a
                  href={`/u/${c.author_handle}`}
                  className="text-foreground hover:text-primary focus-visible:ring-ring/50 rounded font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
                >
                  {c.author_display_name ?? `@${c.author_handle}`}
                </a>
              ) : (
                <span className="text-foreground font-medium">
                  {c.author_display_name ?? "Someone"}
                </span>
              )}
              <span className="text-foreground/60">
                · {timeAgo(c.created_at)}
              </span>
            </div>
            <p className="text-foreground/90 leading-relaxed whitespace-pre-wrap">
              {c.body}
            </p>
          </li>
        ))}
        {list.length === 0 && !comments.isLoading && (
          <li className="text-foreground/70 rounded-lg border border-dashed p-4 text-center text-sm">
            No comments yet — start the discussion.
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
          <label htmlFor="comment-body" className="sr-only">
            Add a comment
          </label>
          <textarea
            id="comment-body"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Add a comment…"
            rows={3}
            className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm leading-relaxed focus-visible:ring-[3px] focus-visible:outline-none"
          />
          {error && (
            <p className="text-destructive text-xs" role="alert">
              {error}
            </p>
          )}
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
        <p className="text-foreground/70 mt-4 text-sm">
          <a
            href="/login"
            className="hover:text-foreground focus-visible:ring-ring/50 rounded underline focus-visible:ring-[3px] focus-visible:outline-none"
          >
            Sign in
          </a>{" "}
          to join the discussion.
        </p>
      )}
    </section>
  );
}
