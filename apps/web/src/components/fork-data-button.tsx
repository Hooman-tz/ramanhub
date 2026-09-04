"use client";

import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitFork } from "lucide-react";

import {
  forkDataset,
  forkFindingData,
  getSession,
  isApiError,
} from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
import { toast } from "@ramanhub/ui/toast";

/**
 * "Fork to my lab" — take a copy of this data and start working on it.
 *
 * Processing pipelines can only be attached to raw files you own, so forking
 * is the only route from "reading someone's post" to "trying my own baseline
 * correction on their data". One call copies every spectrum, replays each
 * one's processing ledger onto the copy, bundles them into a new dataset, and
 * this lands the user in the lab with that dataset already selected — `?d=`
 * and `?mode=` are the params the workbench reads.
 *
 * Two sources, one behaviour: a post (`forkFindingData`, works whether or not
 * the post names a dataset) or a published dataset (`forkDataset`).
 */
export function ForkDataButton({
  source,
  id,
  disabledReason,
  size = "default",
  variant = "default",
  className,
}: {
  source: "finding" | "dataset";
  id: string;
  /** When set, the button renders disabled and explains why. */
  disabledReason?: string;
  size?: "sm" | "default";
  variant?: "default" | "outline";
  className?: string;
}) {
  const router = useRouter();
  const qc = useQueryClient();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: () => getSession(),
  });
  const signedIn = !!session.data;

  const fork = useMutation({
    mutationFn: () =>
      source === "finding" ? forkFindingData(id) : forkDataset(id),
    onSuccess: async (dataset) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["datasets"] }),
        qc.invalidateQueries({ queryKey: ["my-library"] }),
        qc.invalidateQueries({ queryKey: ["wb-library"] }),
      ]);
      toast.success(
        `Forked ${dataset.spectra.length} ${dataset.spectra.length === 1 ? "spectrum" : "spectra"} into "${dataset.name}".`,
      );
      router.push(`/lab?mode=database&d=${encodeURIComponent(dataset.id)}`);
    },
    onError: (e) =>
      toast.error(
        isApiError(e) ? e.message : "Could not fork this data. Try again.",
      ),
  });

  if (!signedIn) {
    return (
      <Button
        asChild
        variant={variant}
        size={size}
        className={className ?? "cursor-pointer gap-1.5"}
      >
        <a href="/login">
          <GitFork className="size-4" aria-hidden />
          Sign in to fork
        </a>
      </Button>
    );
  }

  const disabled = !!disabledReason || fork.isPending;

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      disabled={disabled}
      title={disabledReason}
      onClick={() => fork.mutate()}
      className={className ?? "cursor-pointer gap-1.5"}
    >
      <GitFork className="size-4" aria-hidden />
      {fork.isPending ? "Forking…" : "Fork to my lab"}
    </Button>
  );
}
