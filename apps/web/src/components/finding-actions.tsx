"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowBigUp, Repeat2 } from "lucide-react";

import type { FindingShares, FindingVotes } from "@ramanhub/api-client";
import {
  getFindingShares,
  getFindingVotes,
  getSession,
  toggleFindingShare,
  toggleFindingVote,
} from "@ramanhub/api-client";
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

  const pill =
    "focus-visible:ring-ring/50 border-border inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-full border px-3.5 py-1.5 transition-colors focus-visible:ring-[3px] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none";

  return (
    <div className="mt-5 flex flex-wrap items-center gap-2 text-sm">
      <button
        type="button"
        disabled={!signedIn || voteMutation.isPending}
        onClick={() => voteMutation.mutate()}
        aria-pressed={voted}
        aria-label={voted ? "Remove your vote" : "Vote for this finding"}
        className={cn(
          pill,
          voted
            ? "border-primary/40 bg-primary/10 text-primary"
            : "hover:border-primary/40 hover:bg-muted",
        )}
      >
        <ArrowBigUp className="size-4" aria-hidden />
        <span>{votes.data?.count ?? 0}</span>
      </button>

      <button
        type="button"
        disabled={!signedIn || shareMutation.isPending}
        onClick={() => shareMutation.mutate()}
        aria-pressed={shared}
        aria-label={shared ? "Undo share" : "Share this finding"}
        className={cn(
          pill,
          shared
            ? "border-primary/40 bg-primary/10 text-primary"
            : "hover:border-primary/40 hover:bg-muted",
        )}
      >
        <Repeat2 className="size-4" aria-hidden />
        <span>{shares.data?.count ?? 0}</span>
      </button>

      {!signedIn && (
        <span className="text-foreground/70 text-xs">
          <a
            href="/login"
            className="hover:text-foreground focus-visible:ring-ring/50 rounded underline focus-visible:ring-[3px] focus-visible:outline-none"
          >
            Sign in
          </a>{" "}
          to vote or share
        </span>
      )}
    </div>
  );
}
