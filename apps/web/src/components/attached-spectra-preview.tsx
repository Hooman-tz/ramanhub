"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import { getMyLibrary } from "@ramanhub/api-client";
import { Skeleton } from "@ramanhub/ui/skeleton";

import { SpectrumChart } from "~/components/charts/spectrum-chart";
import { useDatasetBuffers } from "~/lib/spectra-buffer";

/**
 * The traces you just attached, drawn in the composer.
 *
 * Attaching used to be a count — "2 spectra attached" — which is the one thing
 * you can't check. Picking the wrong file from a list of similarly-named scans
 * is easy, and the mistake would only surface once the post was public. The
 * curve is the only reliable confirmation that these are the right ones.
 *
 * Reuses the lab's buffer, so a spectrum already opened in the Data Lab draws
 * here without a request.
 */
export function AttachedSpectraPreview({
  spectrumIds,
  onRemove,
}: {
  spectrumIds: string[];
  onRemove: (spectrumId: string) => void;
}) {
  // Same query key the picker uses, so the titles are already cached by the
  // time anything is attached.
  const library = useQuery({
    queryKey: ["my-library", "picker"],
    queryFn: () => getMyLibrary({ limit: 200 }),
    staleTime: 60_000,
  });

  const { ready, loading } = useDatasetBuffers(spectrumIds);

  const titleFor = useMemo(() => {
    const byId = new Map(
      (library.data ?? []).map((s) => [s.id, s.title ?? "Untitled"]),
    );
    return (id: string) => byId.get(id) ?? id.slice(0, 8);
  }, [library.data]);

  const series = useMemo(
    () =>
      ready.map(({ id, buffer }) => ({
        name: titleFor(id),
        wavenumbers: Array.from(buffer.wavenumbers),
        intensities: Array.from(buffer.intensities),
      })),
    [ready, titleFor],
  );

  if (spectrumIds.length === 0) return null;

  return (
    <div className="border-border space-y-2 rounded-lg border p-2">
      <ul className="flex flex-wrap gap-1.5">
        {spectrumIds.map((id) => (
          <li key={id}>
            <span className="bg-muted inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs">
              <span className="max-w-40 truncate">{titleFor(id)}</span>
              <button
                type="button"
                aria-label={`Remove ${titleFor(id)}`}
                onClick={() => onRemove(id)}
                className="text-muted-foreground hover:text-foreground cursor-pointer"
              >
                <X className="size-3" aria-hidden />
              </button>
            </span>
          </li>
        ))}
      </ul>

      {loading && series.length === 0 ? (
        <Skeleton className="h-[180px] w-full rounded-md" />
      ) : series.length > 0 ? (
        <SpectrumChart
          mode="trace"
          series={series}
          height={180}
          ariaLabel={`Preview of ${series.length} attached ${series.length === 1 ? "spectrum" : "spectra"}`}
        />
      ) : (
        <p className="text-muted-foreground px-2 py-4 text-center text-xs">
          Couldn&apos;t read a chartable trace for a preview. The attachment is
          still fine — this is only the preview.
        </p>
      )}
    </div>
  );
}
