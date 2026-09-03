"use client";

/**
 * Getting a spectrum into the platform.
 *
 * The backend has supported this since Track B; what was missing was any way
 * to reach it from the web. The flow is necessarily multi-step because
 * parsing is asynchronous:
 *
 *   POST /raw-files          -> 202 { raw_file_id, ingestion_job_id }
 *   (worker parses the vendor header out of process)
 *   GET  /ingestion-jobs/id  -> poll until succeeded / failed
 *   PATCH /ingestion-jobs/id -> confirm metadata, creates the draft spectrum
 *
 * The parse step runs in `python -m app.ingestion.worker`, not in the API. If
 * no worker is running the job stays `pending` forever, so this component
 * says so explicitly rather than spinning indefinitely.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  skipToken,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileUp, Loader2 } from "lucide-react";

import type { ExtractedMetadata } from "@ramanhub/api-client";
import {
  confirmIngestionMetadata,
  getIngestionJob,
  isApiError,
  retryIngestionJob,
  updateSpectrum,
  uploadRawFile,
} from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@ramanhub/ui/card";
import { Input } from "@ramanhub/ui/input";
import { Label } from "@ramanhub/ui/label";
import { toast } from "@ramanhub/ui/toast";

/** Mirrors MAX_UPLOAD_SIZE_MB (backend default 50). */
const MAX_UPLOAD_MB = 50;

/**
 * Required by the seeded Raman field registry — the server re-checks this, so
 * these constants only exist to fail fast and to render the right control.
 */
const LASER_WAVELENGTHS = [532, 633, 785, 1064] as const;

/** How long a job may sit `pending` before we suggest the worker is down. */
const STALLED_AFTER_MS = 25_000;

type Draft = Record<string, string>;

const TEXT_FIELDS: {
  key: keyof ExtractedMetadata;
  label: string;
  hint?: string;
}[] = [
  { key: "instrument_vendor", label: "Instrument vendor" },
  { key: "instrument_model", label: "Instrument model" },
  { key: "sample_description", label: "Sample description" },
  {
    key: "spectral_range_cm1",
    label: "Spectral range (cm⁻¹)",
    hint: "Formatted min-max, e.g. 200-3200",
  },
  { key: "acquisition_datetime", label: "Acquired at" },
];

const NUMBER_FIELDS: {
  key: keyof ExtractedMetadata;
  label: string;
  required?: boolean;
}[] = [
  {
    key: "integration_time_ms",
    label: "Integration time (ms)",
    required: true,
  },
  { key: "laser_power_mw", label: "Laser power (mW)" },
  { key: "accumulations", label: "Accumulations" },
  { key: "resolution_cm1", label: "Resolution (cm⁻¹)" },
  { key: "grating_lines_mm", label: "Grating (lines/mm)" },
  { key: "objective_magnification", label: "Objective magnification" },
];

function asString(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number")
    return String(value);
  return "";
}

/** Build the confirm payload, omitting blanks so `extra="forbid"` is happy. */
function toMetadata(draft: Draft): ExtractedMetadata {
  const out: ExtractedMetadata & Record<string, unknown> = {
    modality: "raman",
  };
  for (const { key } of TEXT_FIELDS) {
    const v = draft[key as string]?.trim();
    if (v) out[key as string] = v;
  }
  for (const { key } of NUMBER_FIELDS) {
    const v = draft[key as string]?.trim();
    if (v) out[key as string] = Number(v);
  }
  const laser = draft.laser_wavelength_nm?.trim();
  if (laser) out.laser_wavelength_nm = Number(laser);
  return out;
}

function errorMessage(e: unknown, fallback: string): string {
  return isApiError(e) ? e.message : fallback;
}

export function UploadWizard() {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  /** The record's display name + notes — stored on the Spectrum, not in the
   * parsed acquisition metadata. Seeded from the filename. */
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  /** User edits only. Parsed values are derived, so re-parsing can't be lost. */
  const [edits, setEdits] = useState<Draft>({});
  const [pendingSince, setPendingSince] = useState<number | null>(null);
  const [now, setNow] = useState(() => 0);
  const fileInput = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: (file: File) => uploadRawFile(file),
    onSuccess: (res, file) => {
      setJobId(res.ingestion_job_id);
      setFileName(file.name);
      // Seed the title from the filename (sans extension) so it's never blank.
      setTitle(file.name.replace(/\.[^.]+$/, ""));
      setDescription("");
      setEdits({});
      setPendingSince(Date.now());
      setNow(Date.now());
      toast.success(
        res.deduplicated
          ? "You've uploaded this file before — resuming that job."
          : "Uploaded. Parsing the vendor header…",
      );
    },
    onError: (e) => toast.error(errorMessage(e, "Upload failed.")),
  });

  const job = useQuery({
    queryKey: ["ingestion-job", jobId],
    queryFn: jobId ? () => getIngestionJob(jobId) : skipToken,
    // Poll only while the job can still move.
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "pending" || s === "running" ? 1500 : false;
    },
  });

  const status = job.data?.status;
  const isWaiting = status === "pending" || status === "running";

  // Tick while waiting so `stalled` below can be derived rather than stored —
  // setState in a timer callback is fine, setState in an effect body is not.
  useEffect(() => {
    if (!isWaiting) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [isWaiting]);

  const stalled =
    isWaiting && pendingSince !== null && now - pendingSince > STALLED_AFTER_MS;

  /** Parsed values, derived from the job; user edits win. */
  const parsed = useMemo<Draft>(() => {
    const raw = job.data?.extracted_metadata_raw ?? {};
    const next: Draft = {};
    for (const { key } of [...TEXT_FIELDS, ...NUMBER_FIELDS]) {
      next[key as string] = asString(raw[key as string]);
    }
    next.laser_wavelength_nm = asString(raw.laser_wavelength_nm);
    return next;
  }, [job.data]);

  const draft = useMemo<Draft>(
    () => ({ ...parsed, ...edits }),
    [parsed, edits],
  );

  const confirm = useMutation({
    mutationFn: async (id: string) => {
      const updated = await confirmIngestionMetadata(id, toMetadata(draft));
      // The draft Spectrum now exists; give it a title/description (those live
      // on the record, not in the parsed acquisition metadata).
      const t = title.trim();
      const d = description.trim();
      if (updated.draft_spectrum_id && (t || d)) {
        await updateSpectrum(updated.draft_spectrum_id, {
          title: t || undefined,
          description: d || undefined,
        });
      }
      return updated;
    },
    onSuccess: async (updated) => {
      await qc.invalidateQueries({ queryKey: ["library"] });
      qc.setQueryData(["ingestion-job", updated.id], updated);
      toast.success("Draft spectrum created.");
    },
    onError: (e) => toast.error(errorMessage(e, "Could not save metadata.")),
  });

  const retry = useMutation({
    mutationFn: (id: string) => retryIngestionJob(id),
    onSuccess: () => {
      setPendingSince(Date.now());
      setNow(Date.now());
      void qc.invalidateQueries({ queryKey: ["ingestion-job", jobId] });
      toast.success("Requeued.");
    },
    onError: (e) => toast.error(errorMessage(e, "Could not retry.")),
  });

  const onPick = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
        toast.error(`That file is larger than the ${MAX_UPLOAD_MB} MB limit.`);
        return;
      }
      upload.mutate(file);
    },
    [upload],
  );

  const draftSpectrumId = job.data?.draft_spectrum_id ?? null;
  const canConfirm =
    !!title.trim() &&
    !!draft.laser_wavelength_nm &&
    !!draft.integration_time_ms?.trim() &&
    !confirm.isPending;

  function reset() {
    setJobId(null);
    setEdits({});
    setPendingSince(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  /* ---------------------------------------------------------------- done */
  if (draftSpectrumId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle2 className="size-5 text-emerald-600" aria-hidden />
            Draft spectrum created
          </CardTitle>
          <CardDescription>
            It is private to you until you publish it. Add a title, process it
            in the Lab, then publish when you&apos;re ready.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href={`/spectra/${draftSpectrumId}`}>Open the spectrum</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href={`/lab?s=${draftSpectrumId}`}>Open in the Lab</Link>
          </Button>
          <Button variant="ghost" onClick={reset}>
            Upload another
          </Button>
        </CardContent>
      </Card>
    );
  }

  /* -------------------------------------------------------------- picker */
  if (!jobId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Upload a spectrum</CardTitle>
          <CardDescription>
            A raw vendor file — Renishaw (.wdf), Bruker OPUS, Horiba/generic
            ASCII, and others. Up to {MAX_UPLOAD_MB} MB. The file is stored
            unmodified; everything downstream references it by hash.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <label
            htmlFor="spectrum-file"
            className="border-muted-foreground/25 hover:border-primary/50 hover:bg-accent/40 focus-within:ring-ring flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 text-center transition focus-within:ring-[3px]"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              onPick(e.dataTransfer.files[0]);
            }}
          >
            {upload.isPending ? (
              <Loader2
                className="text-muted-foreground size-8 animate-spin"
                aria-hidden
              />
            ) : (
              <FileUp className="text-muted-foreground size-8" aria-hidden />
            )}
            <span className="text-sm font-medium">
              {upload.isPending
                ? "Uploading…"
                : "Drop a file here, or click to choose"}
            </span>
            <Input
              ref={fileInput}
              id="spectrum-file"
              type="file"
              className="sr-only"
              disabled={upload.isPending}
              onChange={(e) => onPick(e.target.files?.[0])}
            />
          </label>
        </CardContent>
      </Card>
    );
  }

  /* ------------------------------------------------------------- parsing */
  if (job.isLoading || isWaiting) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2 className="size-5 animate-spin" aria-hidden />
            Reading the vendor header
          </CardTitle>
          <CardDescription>
            {status === "running"
              ? "A worker is parsing the file."
              : "Queued for parsing."}
          </CardDescription>
        </CardHeader>
        {stalled && (
          <CardContent>
            <p className="text-foreground rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
              <AlertTriangle
                className="mr-1.5 inline size-4 text-amber-600"
                aria-hidden
              />
              Still queued after {Math.round(STALLED_AFTER_MS / 1000)}s. Parsing
              runs in a separate worker process, not the API — if none is
              running the job never starts. Locally:{" "}
              <code className="bg-muted rounded px-1 py-0.5 text-xs">
                cd backend &amp;&amp; uv run python -m app.ingestion.worker
              </code>
              . Your file is safely stored either way.
            </p>
          </CardContent>
        )}
      </Card>
    );
  }

  /* -------------------------------------------------------------- failed */
  if (status === "failed" || status === "cancelled") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="text-destructive size-5" aria-hidden />
            Could not parse that file
          </CardTitle>
          <CardDescription>
            {job.data?.error_message ??
              "The parser did not recognise this file's format."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button
            onClick={() => jobId && retry.mutate(jobId)}
            disabled={
              retry.isPending ||
              (job.data?.attempt_count ?? 0) >= (job.data?.max_attempts ?? 3)
            }
          >
            {retry.isPending ? "Requeuing…" : "Try again"}
          </Button>
          <Button variant="ghost" onClick={reset}>
            Upload a different file
          </Button>
        </CardContent>
      </Card>
    );
  }

  /* ------------------------------------------------------------- confirm */
  return (
    <Card>
      <CardHeader>
        <CardTitle>Confirm the acquisition metadata</CardTitle>
        {fileName && (
          <div className="text-muted-foreground bg-muted/60 mt-1 inline-flex max-w-full items-center gap-1.5 self-start rounded-md px-2 py-1 text-xs">
            <FileUp className="size-3.5 shrink-0" aria-hidden />
            <span className="truncate font-mono">{fileName}</span>
          </div>
        )}
        <CardDescription>
          {job.data?.parser_used
            ? `Parsed by ${job.data.parser_used}. Check the values — you are the record's author.`
            : "Check the values — you are the record's author."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (jobId) confirm.mutate(jobId);
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="spectrum_title">
              Title <span className="text-destructive">*</span>
            </Label>
            <Input
              id="spectrum_title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Polystyrene reference, 785 nm"
              required
            />
            <p className="text-muted-foreground text-xs">
              How this spectrum is labelled in your library and the feed.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="spectrum_description">Description</Label>
            <textarea
              id="spectrum_description"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional notes about the sample, prep, or conditions."
              className="border-input bg-background focus-visible:ring-ring/50 focus-visible:border-ring w-full rounded-md border px-3 py-2 text-sm leading-relaxed focus-visible:ring-[3px] focus-visible:outline-none"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="laser_wavelength_nm">
              Laser wavelength (nm) <span className="text-destructive">*</span>
            </Label>
            <div className="flex flex-wrap gap-2">
              {LASER_WAVELENGTHS.map((nm) => {
                const active = draft.laser_wavelength_nm === String(nm);
                return (
                  <Button
                    key={nm}
                    type="button"
                    size="sm"
                    variant={active ? "default" : "outline"}
                    aria-pressed={active}
                    onClick={() =>
                      setEdits((d) => ({
                        ...d,
                        laser_wavelength_nm: String(nm),
                      }))
                    }
                  >
                    {nm}
                  </Button>
                );
              })}
            </div>
            <p className="text-muted-foreground text-xs">
              The registry accepts these four excitation lines.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {NUMBER_FIELDS.map(({ key, label, required }) => (
              <div key={key as string} className="space-y-1.5">
                <Label htmlFor={key as string}>
                  {label}
                  {required && <span className="text-destructive"> *</span>}
                </Label>
                <Input
                  id={key as string}
                  inputMode="decimal"
                  value={draft[key as string] ?? ""}
                  onChange={(e) =>
                    setEdits((d) => ({ ...d, [key as string]: e.target.value }))
                  }
                />
              </div>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {TEXT_FIELDS.map(({ key, label, hint }) => (
              <div key={key as string} className="space-y-1.5">
                <Label htmlFor={key as string}>{label}</Label>
                <Input
                  id={key as string}
                  value={draft[key as string] ?? ""}
                  onChange={(e) =>
                    setEdits((d) => ({ ...d, [key as string]: e.target.value }))
                  }
                />
                {hint && (
                  <p className="text-muted-foreground text-xs">{hint}</p>
                )}
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={!canConfirm}>
              {confirm.isPending ? "Saving…" : "Create draft spectrum"}
            </Button>
            <Button type="button" variant="ghost" onClick={reset}>
              Cancel
            </Button>
            {!canConfirm && !confirm.isPending && (
              <span className="text-muted-foreground text-xs">
                Title, laser wavelength and integration time are required.
              </span>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
