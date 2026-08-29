"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getFindingShares,
  getFindingVotes,
  getSession,
  toggleFindingShare,
  toggleFindingVote,
} from "@ramanhub/api-client";
import type { FindingShares, FindingVotes } from "@ramanhub/api-client";

import { cn } from "@ramanhub/ui";

export function FindingActions({
  id,
  initialVotes,
  initialShares,
}: {
  id: string;
  initialVotes?: FindingVotes;
  initialShares?: FindingShares;
}) {
  const qc = useQueryClient();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });
  const signedIn = !!session.data && !session.data.is_guest;

  const votes = useQuery({
    queryKey: ["finding-votes", id],
    queryFn: () => getFindingVotes(id),
    initialData: initialVotes,
  });

  const shares = useQuery({
    queryKey: ["finding-shares", id],
    queryFn: () => getFindingShares(id),
    initialData: initialShares,
  });

  const voteMutation = useMutation({
    mutationFn: () => toggleFindingVote(id),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["finding-votes", id] });
      const prev = qc.getQueryData<FindingVotes>(["finding-votes", id]);
      if (prev) {
        qc.setQueryData<FindingVotes>(["finding-votes", id], {
          voted_by_me: !prev.voted_by_me,
          count: prev.count + (prev.voted_by_me ? -1 : 1),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["finding-votes", id], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["finding-votes", id] });
    },
  });

  const shareMutation = useMutation({
    mutationFn: () => toggleFindingShare(id),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["finding-shares", id] });
      const prev = qc.getQueryData<FindingShares>(["finding-shares", id]);
      if (prev) {
        qc.setQueryData<FindingShares>(["finding-shares", id], {
          shared_by_me: !prev.shared_by_me,
          count: prev.count + (prev.shared_by_me ? -1 : 1),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["finding-shares", id], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["finding-shares", id] });
    },
  });

  const voted = votes.data?.voted_by_me ?? false;
  const shared = shares.data?.shared_by_me ?? false;

  return (
    <div className="mt-4 flex items-center gap-2 text-sm">
      <button
        type="button"
        disabled={!signedIn || voteMutation.isPending}
        onClick={() => voteMutation.mutate()}
        aria-pressed={voted}
        className={cn(
          "border-border inline-flex items-center gap-1.5 rounded-full border px-3 py-1 transition-colors disabled:opacity-60",
          voted
            ? "border-primary/40 bg-primary/10 text-primary"
            : "hover:border-primary/40",
        )}
      >
        <span aria-hidden>▲</span>
        <span>{votes.data?.count ?? 0}</span>
      </button>

      <button
        type="button"
        disabled={!signedIn || shareMutation.isPending}
        onClick={() => shareMutation.mutate()}
        aria-pressed={shared}
        className={cn(
          "border-border inline-flex items-center gap-1.5 rounded-full border px-3 py-1 transition-colors disabled:opacity-60",
          shared
            ? "border-primary/40 bg-primary/10 text-primary"
            : "hover:border-primary/40",
        )}
      >
        <span aria-hidden>↻</span>
        <span>{shares.data?.count ?? 0}</span>
      </button>

      {!signedIn && (
        <span className="text-muted-foreground text-xs">
          <a href="/login" className="hover:text-foreground underline">
            Sign in
          </a>{" "}
          to vote or share
        </span>
      )}
    </div>
  );
}
