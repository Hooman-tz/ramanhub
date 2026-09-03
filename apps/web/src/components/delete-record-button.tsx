"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";

import { deleteFinding, deleteSpectrum, isApiError } from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@ramanhub/ui/dialog";
import { toast } from "@ramanhub/ui/toast";

type Kind = "spectrum" | "finding";

const COPY: Record<Kind, { title: string; body: string; done: string }> = {
  spectrum: {
    title: "Delete this spectrum?",
    body: "This permanently removes the draft, its raw file, processing history and any comments or votes. Published spectra can't be deleted. This can't be undone.",
    done: "Spectrum deleted.",
  },
  finding: {
    title: "Delete this finding?",
    body: "This permanently removes the draft finding and its thread. Published findings can't be deleted. This can't be undone.",
    done: "Finding deleted.",
  },
};

/**
 * Owner-only destructive control with a confirm dialog, mirroring the
 * "Delete account" pattern in `app/settings/page.tsx`. On success it
 * invalidates the library / feed / detail queries and (unless
 * `redirectTo` is null) navigates away.
 */
export function DeleteRecordButton({
  kind,
  id,
  redirectTo = "/office",
  variant = "button",
  className,
}: {
  kind: Kind;
  id: string;
  redirectTo?: string | null;
  variant?: "button" | "icon";
  className?: string;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const del = useMutation({
    mutationFn: () =>
      kind === "spectrum" ? deleteSpectrum(id) : deleteFinding(id),
    onSuccess: async () => {
      setErr(null);
      setOpen(false);
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["my-library"] }),
        qc.invalidateQueries({ queryKey: ["wb-library"] }),
        qc.invalidateQueries({ queryKey: ["library"] }),
        qc.invalidateQueries({ queryKey: ["my-findings"] }),
        qc.invalidateQueries({ queryKey: ["feed"] }),
        qc.invalidateQueries({ queryKey: [kind, id] }),
      ]);
      toast.success(COPY[kind].done);
      if (redirectTo) router.push(redirectTo);
      else router.refresh();
    },
    onError: (e) =>
      setErr(isApiError(e) ? e.message : `Could not delete this ${kind}.`),
  });

  const copy = COPY[kind];

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setErr(null);
      }}
    >
      <DialogTrigger asChild>
        {variant === "icon" ? (
          <Button
            variant="ghost"
            size="icon"
            className={className}
            aria-label={`Delete ${kind}`}
          >
            <Trash2 className="size-4" aria-hidden />
          </Button>
        ) : (
          <Button variant="destructive" size="sm" className={className}>
            Delete {kind}
          </Button>
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.body}</DialogDescription>
        </DialogHeader>
        {err && <p className="text-destructive text-sm">{err}</p>}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="sm">
              Cancel
            </Button>
          </DialogClose>
          <Button
            variant="destructive"
            size="sm"
            disabled={del.isPending}
            onClick={() => del.mutate()}
          >
            {del.isPending ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
