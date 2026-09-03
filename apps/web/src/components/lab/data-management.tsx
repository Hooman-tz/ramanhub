"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, MoreHorizontal, Plus } from "lucide-react";

import type { Dataset, LibrarySpectrum } from "@ramanhub/api-client";
import {
  addDatasetSpectra,
  createDataset,
  deleteDataset,
  deleteSpectrum,
  isApiError,
  removeDatasetSpectrum,
  updateDataset,
} from "@ramanhub/api-client";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@ramanhub/ui/dropdown-menu";
import { Input } from "@ramanhub/ui/input";
import { Label } from "@ramanhub/ui/label";
import { toast } from "@ramanhub/ui/toast";

import { RECORD_DELETE_COPY } from "~/components/delete-record-button";

/**
 * Data management for the lab: create, rename and delete datasets, move
 * spectra between them, and delete a spectrum outright.
 *
 * These live here rather than on the spectrum detail page because the lab is
 * where someone actually works through a project — deciding what belongs in it
 * and what was a bad scan is the same sitting as processing it.
 *
 * Every control here is a thin shell over an endpoint that already enforces
 * the real rules (ownership, modality, caps, published-record protection).
 * The UI never pre-judges those: it sends the request and surfaces whatever
 * the server says, so the two can't drift into disagreeing.
 */

/** Error text for a failed mutation, preferring the API's own message. */
function apiMessage(e: unknown, fallback: string): string {
  return isApiError(e) ? e.message : fallback;
}

const menuTriggerClass =
  "flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none transition-colors duration-150 hover:bg-muted hover:text-foreground focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none";

/* -------------------------------------------------------------------------- */
/* New dataset                                                                */
/* -------------------------------------------------------------------------- */

/**
 * Creates an empty dataset. Empty is deliberate and matches the API: a dataset
 * is a project folder, and the "at least two spectra" rule belongs to an
 * analysis run, not to the container. So you can make the folder first and
 * fill it as scans arrive.
 */
export function NewDatasetButton({
  onCreated,
}: {
  onCreated?: (dataset: Dataset) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () =>
      createDataset({
        name: name.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
      }),
    onSuccess: async (dataset) => {
      await qc.invalidateQueries({ queryKey: ["datasets"] });
      setOpen(false);
      setName("");
      setDescription("");
      setError(null);
      toast.success(`Created ${dataset.name}`);
      onCreated?.(dataset);
    },
    // A duplicate name is a 409 with a useful message; show the server's.
    onError: (e) => setError(apiMessage(e, "Could not create the dataset.")),
  });

  return (
    <>
      <button
        type="button"
        aria-label="New dataset"
        onClick={() => setOpen(true)}
        className={menuTriggerClass}
      >
        <Plus className="size-4" aria-hidden />
      </button>

      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setError(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New dataset</DialogTitle>
            <DialogDescription>
              A folder for one project&apos;s spectra. It can start empty — add
              spectra to it from the list as you go.
            </DialogDescription>
          </DialogHeader>

          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim() && !create.isPending) create.mutate();
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="ds-name">Name</Label>
              <Input
                id="ds-name"
                value={name}
                autoFocus
                maxLength={160}
                placeholder="e.g. Perovskite ageing series"
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="ds-desc">Description (optional)</Label>
              <Input
                id="ds-desc"
                value={description}
                maxLength={2000}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            {error && (
              <p className="text-destructive text-sm" role="alert">
                {error}
              </p>
            )}

            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="outline" size="sm">
                  Cancel
                </Button>
              </DialogClose>
              <Button
                type="submit"
                size="sm"
                disabled={!name.trim() || create.isPending}
              >
                {create.isPending ? "Creating…" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Dataset row menu                                                           */
/* -------------------------------------------------------------------------- */

/** Rename or delete one dataset. */
export function DatasetRowMenu({
  dataset,
  onDeleted,
}: {
  dataset: Dataset;
  onDeleted?: (datasetId: string) => void;
}) {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null);
  const [name, setName] = useState(dataset.name);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setDialog(null);
    setError(null);
  };

  const rename = useMutation({
    mutationFn: () => updateDataset(dataset.id, { name: name.trim() }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["datasets"] });
      close();
      toast.success("Dataset renamed");
    },
    onError: (e) => setError(apiMessage(e, "Could not rename the dataset.")),
  });

  const remove = useMutation({
    mutationFn: () => deleteDataset(dataset.id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["datasets"] });
      close();
      toast.success(`Deleted ${dataset.name}`);
      onDeleted?.(dataset.id);
    },
    // The API refuses (409) when the dataset still has analysis runs, since
    // those are the reproducible record of an analysis. Show that reason.
    onError: (e) => setError(apiMessage(e, "Could not delete the dataset.")),
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Manage ${dataset.name}`}
            onClick={(e) => e.stopPropagation()}
            className={menuTriggerClass}
          >
            <MoreHorizontal className="size-4" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => {
              setName(dataset.name);
              setDialog("rename");
            }}
          >
            Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => setDialog("delete")}
          >
            Delete dataset
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog
        open={dialog === "rename"}
        onOpenChange={(next) => !next && close()}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename dataset</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim() && !rename.isPending) rename.mutate();
            }}
          >
            <div className="space-y-1">
              <Label htmlFor="ds-rename">Name</Label>
              <Input
                id="ds-rename"
                value={name}
                autoFocus
                maxLength={160}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            {error && (
              <p className="text-destructive text-sm" role="alert">
                {error}
              </p>
            )}
            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="outline" size="sm">
                  Cancel
                </Button>
              </DialogClose>
              <Button
                type="submit"
                size="sm"
                disabled={!name.trim() || rename.isPending}
              >
                {rename.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={dialog === "delete"}
        onOpenChange={(next) => !next && close()}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {dataset.name}?</DialogTitle>
            <DialogDescription>
              This removes the folder only. The{" "}
              {dataset.spectra.length === 1
                ? "spectrum in it stays"
                : `${dataset.spectra.length} spectra in it stay`}{" "}
              in your library.
            </DialogDescription>
          </DialogHeader>
          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button
              variant="destructive"
              size="sm"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {remove.isPending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Spectrum row menu                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Per-spectrum management: move it into a dataset, take it out of the one
 * being viewed, or delete it.
 *
 * "Delete spectrum" is hidden for published or DOI-linked records because the
 * API refuses those with a 409 — a published record is citable, so it can't be
 * withdrawn by deletion. Hiding the option states that rule instead of
 * offering an action that always fails.
 */
export function SpectrumRowMenu({
  spectrum,
  datasets,
  activeDataset,
  onDeleted,
}: {
  spectrum: LibrarySpectrum;
  datasets: Dataset[];
  /** The dataset currently scoping the list, if any. */
  activeDataset: Dataset | undefined;
  onDeleted?: (spectrumId: string) => void;
}) {
  const qc = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["datasets"] }),
      qc.invalidateQueries({ queryKey: ["wb-library"] }),
    ]);

  const addTo = useMutation({
    mutationFn: (datasetId: string) =>
      addDatasetSpectra(datasetId, [spectrum.id]),
    onSuccess: async (dataset) => {
      await refresh();
      toast.success(`Added to ${dataset.name}`);
    },
    // Modality mismatch and the per-dataset cap are both enforced server-side
    // and come back with an explanation worth showing verbatim.
    onError: (e) =>
      toast.error(apiMessage(e, "Could not add to that dataset.")),
  });

  const removeFrom = useMutation({
    mutationFn: (datasetId: string) =>
      removeDatasetSpectrum(datasetId, spectrum.id),
    onSuccess: async () => {
      await refresh();
      toast.success("Removed from dataset");
    },
    onError: (e) =>
      toast.error(apiMessage(e, "Could not remove it from the dataset.")),
  });

  const del = useMutation({
    mutationFn: () => deleteSpectrum(spectrum.id),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["datasets"] }),
        qc.invalidateQueries({ queryKey: ["wb-library"] }),
        qc.invalidateQueries({ queryKey: ["my-library"] }),
        qc.invalidateQueries({ queryKey: ["spectrum", spectrum.id] }),
      ]);
      setConfirmDelete(false);
      setError(null);
      toast.success(RECORD_DELETE_COPY.spectrum.done);
      onDeleted?.(spectrum.id);
    },
    onError: (e) => setError(apiMessage(e, "Could not delete this spectrum.")),
  });

  // Datasets this spectrum isn't already in. Adding is idempotent server-side,
  // but offering a no-op would be a worse menu.
  const addable = datasets.filter(
    (d) => !d.spectra.some((s) => s.id === spectrum.id),
  );
  const inActive = activeDataset?.spectra.some((s) => s.id === spectrum.id);
  const deletable = spectrum.state !== "published" && !spectrum.doi;
  const busy = addTo.isPending || removeFrom.isPending;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Manage ${spectrum.title ?? "spectrum"}`}
            disabled={busy}
            className={menuTriggerClass}
          >
            <MoreHorizontal className="size-4" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="gap-2">
              <FolderPlus className="size-4" aria-hidden />
              Add to dataset
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-64 overflow-y-auto">
              {addable.map((d) => (
                <DropdownMenuItem
                  key={d.id}
                  onSelect={() => addTo.mutate(d.id)}
                >
                  <span className="truncate">{d.name}</span>
                </DropdownMenuItem>
              ))}
              {addable.length === 0 && (
                <DropdownMenuItem disabled>
                  {datasets.length === 0
                    ? "No datasets yet"
                    : "Already in every dataset"}
                </DropdownMenuItem>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          {activeDataset && inActive && (
            <DropdownMenuItem
              onSelect={() => removeFrom.mutate(activeDataset.id)}
            >
              <span className="truncate">Remove from {activeDataset.name}</span>
            </DropdownMenuItem>
          )}

          {deletable && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => setConfirmDelete(true)}
              >
                Delete spectrum
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog
        open={confirmDelete}
        onOpenChange={(next) => {
          setConfirmDelete(next);
          if (!next) setError(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{RECORD_DELETE_COPY.spectrum.title}</DialogTitle>
            <DialogDescription>
              {RECORD_DELETE_COPY.spectrum.body}
            </DialogDescription>
          </DialogHeader>
          <p className="text-foreground/80 text-sm font-medium">
            {spectrum.title ?? "Untitled spectrum"}
          </p>
          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
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
    </>
  );
}
