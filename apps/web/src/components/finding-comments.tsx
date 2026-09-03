"use client";

import { useMemo, useState } from "react";
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

function CommentMeta({ c }: { c: FindingComment }) {
  return (
    <div className="mb-1.5 flex items-center gap-2 text-xs">
      {c.author.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={c.author.avatar_url}
          alt=""
          className="size-5 rounded-full object-cover"
        />
      ) : (
        <span
          aria-hidden
          className="bg-muted text-foreground/70 flex size-5 items-center justify-center rounded-full text-[10px] font-semibold"
        >
          {c.author.display_name.trim().charAt(0).toUpperCase() || "?"}
        </span>
      )}
      {c.author.profile_path ? (
        <a
          href={c.author.profile_path}
          className="text-foreground hover:text-primary focus-visible:ring-ring/50 rounded font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none motion-reduce:transition-none"
        >
          {c.author.display_name}
        </a>
      ) : (
        <span className="text-foreground font-medium">
          {c.author.display_name}
        </span>
      )}
      <span className="text-foreground/60">· {timeAgo(c.created_at)}</span>
    </div>
  );
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
  /** Which top-level comment's reply box is open, and its draft text. */
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [replyText, setReplyText] = useState("");

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

  const post = useMutation({
    mutationFn: (vars: { text: string; parentId: number | null }) =>
      postFindingComment(id, {
        body: vars.text.trim(),
        parent_id: vars.parentId ?? undefined,
      }),
    onSuccess: (_data, vars) => {
      setError(null);
      if (vars.parentId === null) {
        setBody("");
      } else {
        setReplyText("");
        setReplyTo(null);
      }
      void qc.invalidateQueries({ queryKey: ["finding-comments", id] });
    },
    onError: (e) =>
      setError(isApiError(e) ? e.message : "Could not post — try again."),
  });

  // Memoized so the `?? []` fallback doesn't hand `useMemo` below a fresh
  // array identity on every render and regroup the thread each time.
  const list = useMemo(() => comments.data ?? [], [comments.data]);

  // The API returns a flat list; group one level of replies under their parent.
  const { roots, repliesByParent } = useMemo(() => {
    const repliesByParent = new Map<number, FindingComment[]>();
    const roots: FindingComment[] = [];
    for (const c of list) {
      if (c.parent_id == null) {
        roots.push(c);
      } else {
        const arr = repliesByParent.get(c.parent_id) ?? [];
        arr.push(c);
        repliesByParent.set(c.parent_id, arr);
      }
    }
    return { roots, repliesByParent };
  }, [list]);

  const busy = post.isPending;

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
        {roots.map((c) => {
          const replies = repliesByParent.get(c.id) ?? [];
          return (
            <li
              key={c.id}
              className="border-border rounded-lg border p-3.5 text-sm"
            >
              <CommentMeta c={c} />
              <p className="text-foreground/90 leading-relaxed whitespace-pre-wrap">
                {c.body}
              </p>

              {signedIn && (
                <button
                  type="button"
                  onClick={() => {
                    setReplyTo(replyTo === c.id ? null : c.id);
                    setReplyText("");
                  }}
                  className="text-foreground/60 hover:text-foreground mt-2 text-xs font-medium"
                >
                  {replyTo === c.id ? "Cancel" : "Reply"}
                </button>
              )}

              {(replies.length > 0 || replyTo === c.id) && (
                <div className="border-border/70 mt-3 space-y-3 border-l-2 pl-3">
                  {replies.map((r) => (
                    <div key={r.id}>
                      <CommentMeta c={r} />
                      <p className="text-foreground/90 leading-relaxed whitespace-pre-wrap">
                        {r.body}
                      </p>
                    </div>
                  ))}

                  {replyTo === c.id && (
                    <form
                      className="space-y-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        if (replyText.trim() && !busy)
                          post.mutate({ text: replyText, parentId: c.id });
                      }}
                    >
                      <textarea
                        value={replyText}
                        onChange={(e) => setReplyText(e.target.value)}
                        placeholder="Write a reply…"
                        rows={2}
                        autoFocus
                        className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm leading-relaxed focus-visible:ring-[3px] focus-visible:outline-none"
                      />
                      <div className="flex justify-end">
                        <Button
                          type="submit"
                          size="sm"
                          disabled={!replyText.trim() || busy}
                        >
                          {busy ? "Posting…" : "Reply"}
                        </Button>
                      </div>
                    </form>
                  )}
                </div>
              )}
            </li>
          );
        })}
        {roots.length === 0 && !comments.isLoading && (
          <li className="text-foreground/70 rounded-lg border border-dashed p-4 text-center text-sm">
            No comments yet — start the discussion.
          </li>
        )}
      </ul>

      {error && (
        <p className="text-destructive mt-2 text-xs" role="alert">
          {error}
        </p>
      )}

      {signedIn ? (
        <form
          className="mt-4 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (body.trim() && !busy)
              post.mutate({ text: body, parentId: null });
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
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={!body.trim() || busy}>
              {busy ? "Posting…" : "Comment"}
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
