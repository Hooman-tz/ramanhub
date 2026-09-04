"use client";

/**
 * Asking the owner what shape their file is.
 *
 * Reached only when automatic detection has already failed — heuristics, then
 * the model on a preview grid, then the model again on a wider slice. At that
 * point the person who ran the instrument is the best remaining source, so we
 * show them the actual cells and let them point at the axis and the spectra.
 *
 * The server checks the answer against the real bytes before accepting it, so
 * a mistake here comes back as a message rather than a broken spectrum. An
 * accepted answer is remembered for the file format, so this question is only
 * ever asked once per format.
 */
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import type {
  FileLayout,
  IngestionJob,
  StructurePreview,
} from "@ramanhub/api-client";
import { declareIngestionJobLayout } from "@ramanhub/api-client";
import { Button } from "@ramanhub/ui/button";
import { Label } from "@ramanhub/ui/label";

type Orientation = FileLayout["orientation"];

const ORIENTATIONS: { value: Orientation; label: string; hint: string }[] = [
  {
    value: "column_major",
    label: "Spectra in columns",
    hint: "One column holds the wavenumbers; each other column is a spectrum.",
  },
  {
    value: "row_major",
    label: "Spectra in rows",
    hint: "One row holds the wavenumbers; each other row is a spectrum.",
  },
  {
    value: "stacked_blocks",
    label: "Stacked blocks",
    hint: "Two-column blocks, one after another, separated by blank lines.",
  },
];

function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  return fallback;
}

export function LayoutDeclaration({
  jobId,
  preview,
  onResolved,
}: {
  jobId: string;
  preview: StructurePreview;
  onResolved: (job: IngestionJob) => void;
}) {
  const [orientation, setOrientation] = useState<Orientation>("column_major");
  const [axis, setAxis] = useState(0);
  const [traces, setTraces] = useState<number[]>(() =>
    // Everything but the first column is the usual answer, and a sensible
    // thing to correct rather than to start from nothing.
    Array.from(
      { length: Math.max(preview.column_count - 1, 0) },
      (_, i) => i + 1,
    ),
  );

  /**
   * What "index" means flips with orientation: columns when spectra run down
   * the file, body rows when they run across it.
   */
  const candidates = useMemo(() => {
    if (orientation === "row_major") {
      return preview.rows.map((_row, index) => index);
    }
    return Array.from({ length: preview.column_count }, (_, index) => index);
  }, [orientation, preview]);

  const selectable = candidates.filter((index) => index !== axis);
  const unit = orientation === "row_major" ? "Row" : "Column";

  const declare = useMutation({
    mutationFn: () =>
      declareIngestionJobLayout(jobId, {
        orientation,
        delimiter: preview.delimiter,
        decimal_separator: preview.decimal_separator,
        header_rows: preview.header_rows,
        x_index: orientation === "stacked_blocks" ? 0 : axis,
        // Row-major files name each spectrum in a leading cell; that cell is
        // not part of the numbers and has to be excluded from both the axis
        // row and every spectrum row.
        label_index: orientation === "row_major" ? 0 : null,
        traces:
          orientation === "stacked_blocks"
            ? Array.from(
                { length: Math.max(preview.blank_separated_blocks, 1) },
                (_, index) => ({ index, label: null }),
              )
            : traces.map((index) => ({ index, label: null })),
      }),
    onSuccess: onResolved,
  });

  const toggle = (index: number) =>
    setTraces((current) =>
      current.includes(index)
        ? current.filter((value) => value !== index)
        : [...current, index].sort((a, b) => a - b),
    );

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label>How is this file arranged?</Label>
        <div className="flex flex-wrap gap-2">
          {ORIENTATIONS.map((option) => (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant={orientation === option.value ? "default" : "outline"}
              aria-pressed={orientation === option.value}
              onClick={() => setOrientation(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <p className="text-muted-foreground text-xs">
          {ORIENTATIONS.find((o) => o.value === orientation)?.hint}
        </p>
      </div>

      <PreviewTable preview={preview} />

      {orientation !== "stacked_blocks" && (
        <>
          <div className="space-y-2">
            <Label>Which {unit.toLowerCase()} holds the wavenumbers?</Label>
            <div className="flex flex-wrap gap-2">
              {candidates.map((index) => (
                <Button
                  key={index}
                  type="button"
                  size="sm"
                  variant={axis === index ? "default" : "outline"}
                  aria-pressed={axis === index}
                  onClick={() => {
                    setAxis(index);
                    setTraces((current) =>
                      current.filter((value) => value !== index),
                    );
                  }}
                >
                  {unit} {index}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label>Which {unit.toLowerCase()}s are spectra?</Label>
            <div className="flex flex-wrap gap-2">
              {selectable.map((index) => (
                <Button
                  key={index}
                  type="button"
                  size="sm"
                  variant={traces.includes(index) ? "default" : "outline"}
                  aria-pressed={traces.includes(index)}
                  onClick={() => toggle(index)}
                >
                  {unit} {index}
                </Button>
              ))}
            </div>
            <p className="text-muted-foreground text-xs">
              Each one becomes its own spectrum. Leave out anything that
              isn&apos;t a measurement — labels, indexes, timestamps.
            </p>
          </div>
        </>
      )}

      {declare.isError && (
        <p className="text-destructive text-sm">
          {errorMessage(
            declare.error,
            "That layout doesn't produce a readable spectrum from this file.",
          )}
        </p>
      )}

      <Button
        onClick={() => declare.mutate()}
        disabled={
          declare.isPending ||
          (orientation !== "stacked_blocks" && traces.length === 0)
        }
      >
        {declare.isPending ? "Checking…" : "Read the file this way"}
      </Button>
    </div>
  );
}

/**
 * The file's actual cells. Column numbers are shown in the header because
 * they are what the controls above refer to — the user should never have to
 * count across a row to work out which index they mean.
 */
function PreviewTable({ preview }: { preview: StructurePreview }) {
  const width = Math.max(
    preview.column_count,
    ...preview.rows.map((row) => row.length),
    ...preview.header_cells.map((row) => row.length),
  );
  const columns = Array.from({ length: width }, (_, index) => index);

  return (
    <div className="space-y-1.5">
      <Label>What we read from your file</Label>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-left font-mono text-xs">
          <thead className="bg-muted/50">
            <tr>
              <th scope="col" className="text-muted-foreground px-2 py-1">
                {" "}
              </th>
              {columns.map((index) => (
                <th
                  scope="col"
                  key={index}
                  className="text-muted-foreground px-2 py-1 font-normal"
                >
                  Col {index}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.header_cells.map((row, rowIndex) => (
              <tr key={`h-${rowIndex}`} className="text-muted-foreground">
                <td className="px-2 py-1">preamble</td>
                {columns.map((index) => (
                  <td key={index} className="px-2 py-1">
                    {row[index] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
            {preview.rows.map((row, rowIndex) => (
              <tr key={`r-${rowIndex}`} className="border-t">
                <td className="text-muted-foreground px-2 py-1">
                  Row {rowIndex}
                </td>
                {columns.map((index) => (
                  <td key={index} className="px-2 py-1">
                    {row[index] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-muted-foreground text-xs">
        {preview.total_lines} lines, {preview.column_count} columns.
        {preview.header_rows > 0 &&
          ` The first ${preview.header_rows} are preamble; row numbering starts after them.`}
        {preview.truncated_rows && " Later rows are not shown."}
      </p>
    </div>
  );
}
