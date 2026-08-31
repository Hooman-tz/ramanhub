"use client";

import type { LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  ListPlus,
  Play,
  Plus,
  RotateCcw,
  Ruler,
  Save,
  Scaling,
  SlidersHorizontal,
  TrendingDown,
  Waves,
  X,
  Zap,
} from "lucide-react";

import type {
  AlgorithmInfo,
  LibrarySpectrum,
  RoutineStep,
} from "@ramanhub/api-client";
import {
  createLedger,
  createRoutine,
  getAlgorithmCatalog,
  getMyLibrary,
  getSpectrum,
  getSpectrumData,
  isApiError,
  listRoutines,
  updateSpectrum,
} from "@ramanhub/api-client";
import { cn } from "@ramanhub/ui";
import { Badge } from "@ramanhub/ui/badge";
import { Button } from "@ramanhub/ui/button";
import { Card } from "@ramanhub/ui/card";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ramanhub/ui/dropdown-menu";
import { Input } from "@ramanhub/ui/input";
import { Label } from "@ramanhub/ui/label";
import { ScrollArea } from "@ramanhub/ui/scroll-area";
import { Skeleton } from "@ramanhub/ui/skeleton";
import { toast } from "@ramanhub/ui/toast";

import { SpectrumChart } from "~/components/charts/spectrum-chart";
import { ReadinessBadge } from "~/components/profile/profile-tabs";

/* --- catalog visual maps --------------------------------------------- */

const CATEGORY_ICON: Record<string, LucideIcon> = {
  despiking: Zap,
  smoothing: Waves,
  baseline: TrendingDown,
  normalization: Scaling,
  axis: Ruler,
};

const CATEGORY_ACCENT: Record<string, string> = {
  despiking: "bg-chart-1",
  smoothing: "bg-chart-2",
  baseline: "bg-chart-3",
  normalization: "bg-chart-4",
  axis: "bg-chart-5",
};

/* --- JSON-Schema helpers ------------------------------------------------- */

interface PropSchema {
  type?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  enum?: (string | number)[];
  title?: string;
  description?: string;
}

function propsOf(schema: Record<string, unknown>): [string, PropSchema][] {
  const p = schema.properties;
  if (p && typeof p === "object")
    return Object.entries(p as Record<string, PropSchema>);
  return [];
}

function humanize(key: string): string {
  const s = key.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Safe stringify for form field values (which are typed `unknown`). */
function asText(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "";
}

function defaultsFor(schema: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, p] of propsOf(schema))
    if (p.default !== undefined) out[k] = p.default;
  return out;
}

/** Drop blank values and coerce numeric strings before sending to the API. */
function cleanParams(
  raw: Record<string, unknown>,
  schema: Record<string, unknown>,
): Record<string, unknown> {
  const known = new Map(propsOf(schema));
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (v === "" || v === undefined || v === null) continue;
    const ps = known.get(k);
    if (ps && (ps.type === "number" || ps.type === "integer")) {
      const n = typeof v === "number" ? v : Number(v);
      if (Number.isNaN(n)) continue;
      out[k] = ps.type === "integer" ? Math.round(n) : n;
    } else {
      out[k] = v;
    }
  }
  return out;
}

function extent(a: number[]): [number, number] {
  let lo = Number.POSITIVE_INFINITY;
  let hi = Number.NEGATIVE_INFINITY;
  for (const v of a) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return [lo, hi];
}

/* --- pipeline model ---------------------------------------------------- */

interface PipeStep {
  uid: string;
  spec: AlgorithmInfo;
  params: Record<string, unknown>;
}

let uidSeq = 0;
const nextUid = () => `step-${++uidSeq}`;

const PAGE = 20;
const iconBtn =
  "flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none transition-colors duration-150 hover:bg-muted hover:text-foreground focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-40 motion-reduce:transition-none";

/* -------------------------------------------------------------------------- */

export function Workbench() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const qc = useQueryClient();

  const selectedId = searchParams.get("s");

  /* left pane — files */
  const [showFilters, setShowFilters] = useState(false);
  const [matDraft, setMatDraft] = useState("");
  const [snrDraft, setSnrDraft] = useState("");
  const [libFilters, setLibFilters] = useState<{
    material_type?: string;
    min_snr?: number;
  }>({});

  const lib = useInfiniteQuery({
    queryKey: ["wb-library", libFilters],
    queryFn: ({ pageParam }) =>
      getMyLibrary({ ...libFilters, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) =>
      last.length === PAGE ? all.length * PAGE : undefined,
  });
  const rows: LibrarySpectrum[] = lib.data?.pages.flat() ?? [];
  const selectedRow = rows.find((r) => r.id === selectedId);
  const rawFileId = selectedRow?.raw_file_id;

  /* center pane — curve */
  const [view, setView] = useState<"raw" | "processed">("raw");
  const [appliedCount, setAppliedCount] = useState<number | null>(null);

  // Reset the view when the selected spectrum changes — the sanctioned
  // "adjust state during render" pattern rather than a cascading effect.
  const [seenId, setSeenId] = useState(selectedId);
  if (selectedId !== seenId) {
    setSeenId(selectedId);
    setView("raw");
    setAppliedCount(null);
  }

  const spectrum = useQuery({
    queryKey: ["spectrum", selectedId],
    queryFn: () => {
      if (!selectedId) throw new Error("No spectrum selected.");
      return getSpectrum(selectedId);
    },
    enabled: !!selectedId,
  });

  const wantRaw = view === "raw";
  const data = useQuery({
    queryKey: ["spectrum-data", selectedId, wantRaw],
    queryFn: () => {
      if (!selectedId) throw new Error("No spectrum selected.");
      return getSpectrumData(selectedId, { raw: wantRaw, maxPoints: 4000 });
    },
    enabled: !!selectedId,
  });

  /* right pane — pipeline */
  const catalog = useQuery({
    queryKey: ["algorithms"],
    queryFn: () => getAlgorithmCatalog(),
  });
  const routines = useQuery({
    queryKey: ["routines"],
    queryFn: () => listRoutines(),
  });

  const [pipeline, setPipeline] = useState<PipeStep[]>([]);
  const [routineName, setRoutineName] = useState("");

  const steps: RoutineStep[] = useMemo(
    () =>
      pipeline.map((p, i) => ({
        type: p.spec.step_type,
        params: cleanParams(p.params, p.spec.param_schema),
        order: i,
      })),
    [pipeline],
  );

  const applyMut = useMutation({
    mutationFn: async () => {
      if (!rawFileId || !selectedId)
        throw new Error("Select a spectrum first.");
      const ledger = await createLedger(rawFileId, steps);
      await updateSpectrum(selectedId, {
        current_ledger_id: ledger.ledger_id,
      });
      return ledger;
    },
    onSuccess: () => {
      setAppliedCount(steps.length);
      setView("processed");
      void qc.invalidateQueries({ queryKey: ["spectrum-data", selectedId] });
      void qc.invalidateQueries({ queryKey: ["spectrum", selectedId] });
      toast.success(
        `Applied ${steps.length} step${steps.length === 1 ? "" : "s"}`,
      );
    },
    onError: (e) =>
      toast.error(isApiError(e) ? e.message : "Could not apply the pipeline."),
  });

  const resetMut = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error("Select a spectrum first.");
      return updateSpectrum(selectedId, { current_ledger_id: null });
    },
    onSuccess: () => {
      setAppliedCount(null);
      setView("raw");
      void qc.invalidateQueries({ queryKey: ["spectrum-data", selectedId] });
      void qc.invalidateQueries({ queryKey: ["spectrum", selectedId] });
      toast.success("Reset to raw");
    },
    onError: (e) => toast.error(isApiError(e) ? e.message : "Could not reset."),
  });

  const saveMut = useMutation({
    mutationFn: () =>
      createRoutine({
        modality: selectedRow?.modality ?? spectrum.data?.modality ?? "raman",
        name: routineName.trim(),
        steps_template: steps,
      }),
    onSuccess: () => {
      setRoutineName("");
      void qc.invalidateQueries({ queryKey: ["routines"] });
      toast.success("Routine saved");
    },
    onError: (e) =>
      toast.error(isApiError(e) ? e.message : "Could not save routine."),
  });

  /* actions */
  function select(id: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", "workbench");
    params.set("s", id);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  function applyFilters() {
    const f: { material_type?: string; min_snr?: number } = {};
    if (matDraft.trim()) f.material_type = matDraft.trim();
    const n = Number(snrDraft);
    if (snrDraft.trim() && !Number.isNaN(n)) f.min_snr = n;
    setLibFilters(f);
  }

  function addStep(spec: AlgorithmInfo) {
    setPipeline((p) => [
      ...p,
      { uid: nextUid(), spec, params: defaultsFor(spec.param_schema) },
    ]);
  }

  function removeStep(uid: string) {
    setPipeline((p) => p.filter((s) => s.uid !== uid));
  }

  function move(uid: string, dir: -1 | 1) {
    setPipeline((p) => {
      const i = p.findIndex((s) => s.uid === uid);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= p.length) return p;
      const a = p[i];
      const b = p[j];
      if (!a || !b) return p;
      const next = [...p];
      next[i] = b;
      next[j] = a;
      return next;
    });
  }

  function setParam(uid: string, key: string, value: unknown) {
    setPipeline((p) =>
      p.map((s) =>
        s.uid === uid ? { ...s, params: { ...s.params, [key]: value } } : s,
      ),
    );
  }

  function loadRoutine(tpl: RoutineStep[]) {
    const algs = catalog.data?.algorithms ?? [];
    const next: PipeStep[] = [];
    for (const st of [...tpl].sort((x, y) => x.order - y.order)) {
      const spec = algs.find((a) => a.step_type === st.type);
      if (spec)
        next.push({
          uid: nextUid(),
          spec,
          params: { ...defaultsFor(spec.param_schema), ...st.params },
        });
    }
    setPipeline(next);
  }

  const wn = data.data?.wavenumbers;
  const range =
    wn && wn.length > 0
      ? (() => {
          const [lo, hi] = extent(wn);
          return `${Math.round(lo)}–${Math.round(hi)} cm⁻¹`;
        })()
      : "";

  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
      {/* -------- Left: Files -------- */}
      <Card className="flex max-h-[70vh] flex-col gap-0 overflow-hidden p-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:w-[300px] lg:shrink-0">
        <div className="bg-card flex items-center justify-between gap-2 border-b px-3 py-2">
          <h3 className="text-sm font-semibold">My spectra</h3>
          <button
            type="button"
            aria-label={showFilters ? "Hide filters" : "Show filters"}
            aria-expanded={showFilters}
            onClick={() => setShowFilters((v) => !v)}
            className={iconBtn}
          >
            <SlidersHorizontal className="size-4" aria-hidden />
          </button>
        </div>

        {showFilters && (
          <div className="space-y-2 border-b px-3 py-2">
            <div className="space-y-1">
              <Label htmlFor="wb-mat" className="text-xs">
                Material
              </Label>
              <Input
                id="wb-mat"
                value={matDraft}
                onChange={(e) => setMatDraft(e.target.value)}
                className="h-8"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="wb-snr" className="text-xs">
                Min SNR
              </Label>
              <Input
                id="wb-snr"
                type="number"
                value={snrDraft}
                onChange={(e) => setSnrDraft(e.target.value)}
                className="h-8"
              />
            </div>
            <Button size="sm" className="w-full" onClick={applyFilters}>
              Apply filters
            </Button>
          </div>
        )}

        <ScrollArea className="min-h-0 flex-1">
          <div className="p-2">
            {lib.isLoading && (
              <div className="space-y-2">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-14 w-full rounded-lg" />
                ))}
              </div>
            )}

            {!lib.isLoading && rows.length === 0 && (
              <p className="text-muted-foreground p-4 text-center text-xs">
                No spectra yet — upload one to start processing.
              </p>
            )}

            <ul className="space-y-1">
              {rows.map((s) => {
                const sel = s.id === selectedId;
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      aria-pressed={sel}
                      onClick={() => select(s.id)}
                      className={cn(
                        "flex w-full cursor-pointer flex-col gap-1 rounded-lg px-2 py-2 text-left transition-colors duration-150 outline-none",
                        "focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none",
                        sel ? "bg-muted" : "hover:bg-muted/60",
                      )}
                    >
                      <span className="truncate text-sm font-medium">
                        {s.title ?? "Untitled"}
                      </span>
                      <span className="flex flex-wrap items-center gap-1.5">
                        {s.material_type && (
                          <Badge
                            variant="outline"
                            className="text-[0.7rem] font-normal"
                          >
                            {s.material_type}
                          </Badge>
                        )}
                        <span className="text-muted-foreground text-xs">
                          SNR {s.snr != null ? Math.round(s.snr) : "—"}
                        </span>
                        <ReadinessBadge s={s} />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>

            {lib.hasNextPage && (
              <Button
                variant="outline"
                size="sm"
                className="mt-2 w-full"
                disabled={lib.isFetchingNextPage}
                onClick={() => void lib.fetchNextPage()}
              >
                {lib.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            )}
          </div>
        </ScrollArea>
      </Card>

      {/* -------- Center: Spectrum -------- */}
      <Card className="min-w-0 flex-1 gap-3 p-3">
        {!selectedId ? (
          <div className="flex h-[360px] flex-col items-center justify-center gap-2 text-center">
            <SlidersHorizontal
              className="text-muted-foreground size-8"
              aria-hidden
            />
            <p className="text-muted-foreground text-sm">
              Select a spectrum from the left to preview and process it.
            </p>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="truncate text-sm font-semibold">
                  {spectrum.data?.title ?? selectedRow?.title ?? "Spectrum"}
                </h3>
                <p className="text-muted-foreground text-xs">
                  {spectrum.data?.material_type ??
                    selectedRow?.material_type ??
                    "—"}
                  {spectrum.data?.doi ? ` · DOI ${spectrum.data.doi}` : ""}
                </p>
              </div>

              <div
                className="flex overflow-hidden rounded-md border"
                role="group"
                aria-label="Curve view"
              >
                <button
                  type="button"
                  aria-pressed={view === "raw"}
                  onClick={() => setView("raw")}
                  className={cn(
                    "min-h-9 cursor-pointer px-3 text-xs font-medium transition-colors duration-150 outline-none",
                    "focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none",
                    view === "raw"
                      ? "bg-primary text-primary-foreground"
                      : "bg-background hover:bg-muted",
                  )}
                >
                  Raw
                </button>
                <button
                  type="button"
                  aria-pressed={view === "processed"}
                  disabled={appliedCount == null}
                  onClick={() => setView("processed")}
                  className={cn(
                    "min-h-9 cursor-pointer border-l px-3 text-xs font-medium transition-colors duration-150 outline-none",
                    "focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none",
                    "disabled:cursor-not-allowed disabled:opacity-50",
                    view === "processed"
                      ? "bg-primary text-primary-foreground"
                      : "bg-background hover:bg-muted",
                  )}
                >
                  Processed{appliedCount != null ? ` (${appliedCount})` : ""}
                </button>
              </div>
            </div>

            <div className="rounded-lg border p-2">
              {!data.data && data.isLoading ? (
                <Skeleton className="h-[360px] w-full" />
              ) : data.data ? (
                <SpectrumChart
                  mode="trace"
                  wavenumbers={data.data.wavenumbers}
                  intensities={data.data.intensities}
                  height={360}
                  loading={data.isFetching}
                  ariaLabel={`${view} spectrum trace`}
                />
              ) : (
                <p className="text-muted-foreground p-4 text-center text-sm">
                  Could not load spectrum data.
                </p>
              )}
            </div>

            {data.data && (
              <p className="text-muted-foreground text-xs">
                {data.data.wavenumbers.length.toLocaleString()} of{" "}
                {data.data.total_points.toLocaleString()} points
                {data.data.downsampled ? " · downsampled for display" : ""}
                {range ? ` · ${range}` : ""}
              </p>
            )}
          </>
        )}
      </Card>

      {/* -------- Right: Pipeline -------- */}
      <Card className="flex max-h-[75vh] flex-col gap-0 overflow-hidden p-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:w-[320px] lg:shrink-0">
        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-3 p-3">
            {/* Tool palette */}
            <div>
              <h3 className="mb-2 text-sm font-semibold">Tools</h3>
              {catalog.isLoading && (
                <div className="space-y-2">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-12 w-full rounded-lg" />
                  ))}
                </div>
              )}
              {catalog.data && (
                <PaletteGroups
                  categories={catalog.data.categories}
                  algorithms={catalog.data.algorithms}
                  onAdd={addStep}
                />
              )}
            </div>

            {/* Pipeline */}
            <div className="border-t pt-3">
              <h3 className="mb-2 text-sm font-semibold">
                Pipeline{pipeline.length > 0 ? ` (${pipeline.length})` : ""}
              </h3>
              {pipeline.length === 0 ? (
                <p className="text-muted-foreground rounded-lg border border-dashed p-3 text-center text-xs">
                  Add tools above to build a processing pipeline.
                </p>
              ) : (
                <ol className="space-y-2">
                  {pipeline.map((step, i) => (
                    <li key={step.uid} className="rounded-lg border">
                      <div className="flex items-stretch gap-2">
                        <span
                          className={cn(
                            "w-1 shrink-0 rounded-l-lg",
                            CATEGORY_ACCENT[step.spec.category] ?? "bg-muted",
                          )}
                          aria-hidden
                        />
                        <div className="min-w-0 flex-1 py-2 pr-2">
                          <div className="flex items-center gap-1">
                            <span className="min-w-0 flex-1 truncate text-xs font-medium">
                              {i + 1}. {step.spec.label}
                            </span>
                            <button
                              type="button"
                              aria-label={`Move ${step.spec.label} up`}
                              disabled={i === 0}
                              onClick={() => move(step.uid, -1)}
                              className={iconBtn}
                            >
                              <ChevronUp className="size-3.5" aria-hidden />
                            </button>
                            <button
                              type="button"
                              aria-label={`Move ${step.spec.label} down`}
                              disabled={i === pipeline.length - 1}
                              onClick={() => move(step.uid, 1)}
                              className={iconBtn}
                            >
                              <ChevronDown className="size-3.5" aria-hidden />
                            </button>
                            <button
                              type="button"
                              aria-label={`Remove ${step.spec.label}`}
                              onClick={() => removeStep(step.uid)}
                              className={iconBtn}
                            >
                              <X className="size-3.5" aria-hidden />
                            </button>
                          </div>
                          <ParamForm
                            uid={step.uid}
                            schema={step.spec.param_schema}
                            values={step.params}
                            onChange={setParam}
                          />
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        </ScrollArea>

        {/* Actions */}
        <div className="bg-card flex flex-wrap gap-2 border-t p-2">
          <Button
            size="sm"
            disabled={pipeline.length === 0 || !rawFileId || applyMut.isPending}
            onClick={() => applyMut.mutate()}
          >
            <Play className="size-4" aria-hidden />
            {applyMut.isPending ? "Applying…" : "Apply"}
          </Button>

          <Button
            size="sm"
            variant="outline"
            disabled={!selectedId || resetMut.isPending}
            onClick={() => resetMut.mutate()}
          >
            <RotateCcw className="size-4" aria-hidden />
            Reset to raw
          </Button>

          <Dialog>
            <DialogTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                disabled={pipeline.length === 0}
              >
                <Save className="size-4" aria-hidden />
                Save as routine
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Save pipeline as routine</DialogTitle>
                <DialogDescription>
                  Store the current {pipeline.length}-step pipeline so you can
                  re-apply it to other spectra.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-2">
                <Label htmlFor="wb-routine-name">Routine name</Label>
                <Input
                  id="wb-routine-name"
                  value={routineName}
                  onChange={(e) => setRoutineName(e.target.value)}
                  placeholder="e.g. Baseline + SNV"
                />
              </div>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline" size="sm">
                    Cancel
                  </Button>
                </DialogClose>
                <DialogClose asChild>
                  <Button
                    size="sm"
                    disabled={!routineName.trim() || saveMut.isPending}
                    onClick={() => saveMut.mutate()}
                  >
                    Save
                  </Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                disabled={(routines.data?.length ?? 0) === 0}
              >
                <ListPlus className="size-4" aria-hidden />
                Load routine
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {(routines.data ?? []).map((r) => (
                <DropdownMenuItem
                  key={r.id}
                  onSelect={() => loadRoutine(r.steps_template)}
                >
                  {r.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function PaletteGroups({
  categories,
  algorithms,
  onAdd,
}: {
  categories: string[];
  algorithms: AlgorithmInfo[];
  onAdd: (spec: AlgorithmInfo) => void;
}) {
  return (
    <div className="space-y-3">
      {categories.map((cat) => {
        const algs = algorithms.filter((a) => a.category === cat);
        if (algs.length === 0) return null;
        const Icon = CATEGORY_ICON[cat] ?? SlidersHorizontal;
        return (
          <div key={cat}>
            <p className="text-muted-foreground mb-1 text-[0.7rem] font-medium tracking-wide uppercase">
              {cat}
            </p>
            <div className="space-y-1.5">
              {algs.map((a) => (
                <button
                  key={a.step_type}
                  type="button"
                  onClick={() => onAdd(a)}
                  className={cn(
                    "group flex w-full cursor-pointer items-start gap-2 rounded-lg border p-2 text-left transition-colors duration-150 outline-none",
                    "hover:border-primary/40 hover:bg-muted/50 focus-visible:ring-ring/50 focus-visible:ring-[3px] motion-reduce:transition-none",
                  )}
                >
                  <Icon
                    className="text-muted-foreground mt-0.5 size-4 shrink-0"
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="truncate text-xs font-medium">
                        {a.label}
                      </span>
                      {a.transforms_axis && (
                        <Badge
                          variant="outline"
                          className="shrink-0 text-[0.65rem] font-normal"
                        >
                          changes axis
                        </Badge>
                      )}
                    </span>
                    <span
                      className="text-muted-foreground line-clamp-1 text-[0.7rem]"
                      title={a.description}
                    >
                      {a.description}
                    </span>
                  </span>
                  <Plus
                    className="text-muted-foreground group-hover:text-primary size-4 shrink-0"
                    aria-hidden
                  />
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function ParamForm({
  uid,
  schema,
  values,
  onChange,
}: {
  uid: string;
  schema: Record<string, unknown>;
  values: Record<string, unknown>;
  onChange: (uid: string, key: string, value: unknown) => void;
}) {
  const entries = propsOf(schema);
  if (entries.length === 0)
    return (
      <p className="text-muted-foreground mt-1 text-[0.7rem]">No parameters.</p>
    );

  return (
    <div className="mt-2 space-y-2">
      {entries.map(([key, p]) => {
        const id = `p-${uid}-${key}`;
        const label = p.title ?? humanize(key);
        const cur = values[key];

        if (p.type === "boolean") {
          return (
            <div key={key} className="flex items-start gap-2">
              <input
                id={id}
                type="checkbox"
                className="accent-primary mt-0.5 size-4 cursor-pointer"
                checked={cur === undefined ? Boolean(p.default) : Boolean(cur)}
                onChange={(e) => onChange(uid, key, e.target.checked)}
              />
              <span className="min-w-0">
                <Label htmlFor={id} className="text-[0.7rem] leading-tight">
                  {label}
                </Label>
                {p.description && (
                  <span className="text-muted-foreground block text-[0.65rem]">
                    {p.description}
                  </span>
                )}
              </span>
            </div>
          );
        }

        if (Array.isArray(p.enum)) {
          return (
            <div key={key} className="space-y-1">
              <Label htmlFor={id} className="text-[0.7rem]">
                {label}
              </Label>
              <select
                id={id}
                value={asText(cur ?? p.default)}
                onChange={(e) => onChange(uid, key, e.target.value)}
                className="border-input bg-background focus-visible:ring-ring/50 h-8 w-full rounded-md border px-2 text-xs outline-none focus-visible:ring-[3px]"
              >
                {p.enum.map((opt) => (
                  <option key={asText(opt)} value={asText(opt)}>
                    {asText(opt)}
                  </option>
                ))}
              </select>
              {p.description && (
                <p className="text-muted-foreground text-[0.65rem]">
                  {p.description}
                </p>
              )}
            </div>
          );
        }

        if (p.type === "number" || p.type === "integer") {
          const step = p.type === "integer" ? 1 : "any";
          const val = asText(cur);
          return (
            <div key={key} className="space-y-1">
              <Label htmlFor={id} className="text-[0.7rem]">
                {label}
              </Label>
              <Input
                id={id}
                type="number"
                value={val}
                min={p.minimum}
                max={p.maximum}
                step={step}
                onChange={(e) =>
                  onChange(
                    uid,
                    key,
                    e.target.value === "" ? "" : Number(e.target.value),
                  )
                }
                className="h-8 text-xs"
              />
              {typeof p.minimum === "number" &&
                typeof p.maximum === "number" && (
                  <input
                    type="range"
                    aria-label={`${label} slider`}
                    min={p.minimum}
                    max={p.maximum}
                    step={
                      p.type === "integer" ? 1 : (p.maximum - p.minimum) / 100
                    }
                    value={
                      typeof cur === "number"
                        ? cur
                        : Number(p.default ?? p.minimum)
                    }
                    onChange={(e) => onChange(uid, key, Number(e.target.value))}
                    className="accent-primary w-full cursor-pointer"
                  />
                )}
              {p.description && (
                <p className="text-muted-foreground text-[0.65rem]">
                  {p.description}
                </p>
              )}
            </div>
          );
        }

        if (p.type === "object") {
          return (
            <p
              key={key}
              className="text-muted-foreground text-[0.65rem] italic"
            >
              {label}: configured via the API — not editable in the workbench.
            </p>
          );
        }

        return (
          <div key={key} className="space-y-1">
            <Label htmlFor={id} className="text-[0.7rem]">
              {label}
            </Label>
            <Input
              id={id}
              value={asText(cur ?? p.default)}
              onChange={(e) => onChange(uid, key, e.target.value)}
              className="h-8 text-xs"
            />
            {p.description && (
              <p className="text-muted-foreground text-[0.65rem]">
                {p.description}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
