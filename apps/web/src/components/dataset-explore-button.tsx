"use client";

import type { ExplorerSpectrum } from "~/components/charts/spectrum-explorer";
import { SpectrumExplorer } from "~/components/charts/spectrum-explorer";

/**
 * Thin client wrapper so the server-rendered dataset page can drop in the
 * explorer without becoming a client component itself.
 */
export function DatasetExploreButton({
  name,
  spectra,
}: {
  name: string;
  spectra: ExplorerSpectrum[];
}) {
  return <SpectrumExplorer spectra={spectra} title={name} />;
}
