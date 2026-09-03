"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Boxes, Check } from "lucide-react";

import type { LibrarySpectrum } from "@ramanhub/api-client";
import { getMyLibrary, listDatasets } from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Badge } from "@ramanhub/ui/badge";
import { Button } from "@ramanhub/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ramanhub/ui/dialog";
import { ScrollArea } from "@ramanhub/ui/scroll-area";
import { Skeleton } from "@ramanhub/ui/skeleton";

/**
 * Pick spectra to attach to a write-up, browsing by dataset.
 *
 * Scoped by dataset because that is how the work is organised — you attach
 * "the three from the ageing series", not "whichever of my 200 files I can
 * remember the title of".
 *
 * Publication state is shown rather than filtered. A draft spectrum can be
 * attached to a draft finding perfectly well; it only blocks *publishing*,
 * and the publish step says so. Hiding drafts here would make it impossible
 * to assemble a write-up before releasing its data, which is the normal order
 * of work.
 */
export function SpectrumPickerDialog({
  open,
  onOpenChange,
  onConfirm,
  /** Already attached — shown ticked and not re-added. */
  alreadyAttached = [],
  confirmLabel = "Attach",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (spectrumIds: string[]) => void;
  alreadyAttached?: string[];
  confirmLabel?: string;
}) {
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const datasets = useQuery({
    queryKey: ["datasets"],
    queryFn: () => listDatasets(),
    enabled: open,
  });

  const library = useQuery({
    queryKey: ["my-library", "picker"],
    queryFn: () => getMyLibrary({ limit: 200 }),
    enabled: open,
  });

  const selectedDataset = datasets.data?.find((d) => d.id === datasetId);
  const rows: LibrarySpectrum[] = useMemo(() => {
    const all = library.data ?? [];
    if (!selectedDataset) return all;
    const members = new Set(selectedDataset.spectra.map((s) => s.id));
    return all.filter((r) => members.has(r.id));
  }, [library.data, selectedDataset]);

  const attached = useMemo(() => new Set(alreadyAttached), [alreadyAttached]);

  const toggle = (id: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const close = () => {
    onOpenChange(false);
    setPicked(new Set());
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setPicked(new Set());
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Attach spectra</DialogTitle>
          <DialogDescription>
            Pick from a dataset, or browse everything you own.
          </DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 gap-3">
          <div className="w-40 shrink-0 border-r pr-2">
            <ScrollArea className="h-72">
              <ul className="space-y-1 pr-2">
                <li>
                  <button
                    type="button"
                    aria-pressed={!datasetId}
                    onClick={() => setDatasetId(null)}
                    className={cn(
                      "w-full cursor-pointer rounded-md px-2 py-1.5 text-left text-xs transition-colors duration-150",
                      !datasetId ? "bg-muted font-medium" : "hover:bg-muted/60",
                    )}
                  >
                    All spectra
                  </button>
                </li>
                {(datasets.data ?? []).map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      aria-pressed={d.id === datasetId}
                      onClick={() => setDatasetId(d.id)}
                      className={cn(
                        "flex w-full cursor-pointer items-center justify-between gap-1 rounded-md px-2 py-1.5 text-left text-xs transition-colors duration-150",
                        d.id === datasetId
                          ? "bg-muted font-medium"
                          : "hover:bg-muted/60",
                      )}
                    >
                      <span className="truncate">{d.name}</span>
                      <span className="text-muted-foreground tabular-nums">
                        {d.spectra.length}
                      </span>
                    </button>
                  </li>
                ))}
                {datasets.isLoading && <Skeleton className="h-7 w-full" />}
                {!datasets.isLoading && (datasets.data?.length ?? 0) === 0 && (
                  <li className="text-muted-foreground px-2 py-1.5 text-[11px]">
                    <Boxes className="mb-1 size-3.5" aria-hidden />
                    <br />
                    No datasets yet.
                  </li>
                )}
              </ul>
            </ScrollArea>
          </div>

          <div className="min-w-0 flex-1">
            <ScrollArea className="h-72">
              {library.isLoading ? (
                <div className="space-y-2 pr-2">
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-11 w-full rounded-lg" />
                  ))}
                </div>
              ) : rows.length === 0 ? (
                <p className="text-muted-foreground p-4 text-center text-sm">
                  {selectedDataset
                    ? `Nothing in ${selectedDataset.name}.`
                    : "No spectra yet — upload one first."}
                </p>
              ) : (
                <ul className="space-y-1 pr-2">
                  {rows.map((s) => {
                    const isAttached = attached.has(s.id);
                    const isPicked = picked.has(s.id);
                    return (
                      <li key={s.id}>
                        <button
                          type="button"
                          disabled={isAttached}
                          aria-pressed={isPicked}
                          onClick={() => toggle(s.id)}
                          className={cn(
                            "flex w-full cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors duration-150",
                            "disabled:cursor-not-allowed disabled:opacity-50",
                            isPicked ? "bg-muted" : "hover:bg-muted/60",
                          )}
                        >
                          <span
                            className={cn(
                              "flex size-4 shrink-0 items-center justify-center rounded border",
                              isPicked || isAttached
                                ? "bg-primary border-primary text-primary-foreground"
                                : "border-input",
                            )}
                            aria-hidden
                          >
                            {(isPicked || isAttached) && (
                              <Check className="size-3" />
                            )}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium">
                              {s.title ?? "Untitled"}
                            </span>
                            <span className="text-muted-foreground text-xs">
                              {s.material_type ?? "—"}
                              {isAttached ? " · already attached" : ""}
                            </span>
                          </span>
                          <Badge
                            variant={
                              s.state === "published" ? "secondary" : "outline"
                            }
                            className="shrink-0 text-[0.7rem] font-normal capitalize"
                          >
                            {s.state}
                          </Badge>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </ScrollArea>
          </div>
        </div>

        <DialogFooter className="sm:justify-between">
          <p className="text-muted-foreground text-xs">
            {picked.size > 0
              ? `${picked.size} selected`
              : "Drafts can be attached; they only block publishing."}
          </p>
          <div className="flex gap-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button
              size="sm"
              disabled={picked.size === 0}
              onClick={() => {
                onConfirm([...picked]);
                close();
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
