"use client";

import dynamic from "next/dynamic";

import {
  HERO_INTENSITIES,
  HERO_MARKERS,
  HERO_WAVENUMBERS,
} from "./hero-spectrum-data";

/**
 * ECharts is a heavy dependency and this is the most LCP-sensitive page we
 * have, so the chart loads after the shell rather than inside the initial
 * chunk. `ssr: false` is only legal inside a client component, which is the
 * entire reason this thin wrapper exists — `landing.tsx` is a server component.
 */
const SpectrumChart = dynamic(
  () => import("~/components/charts/spectrum-chart").then((m) => m.SpectrumChart),
  {
    ssr: false,
    loading: () => (
      <div
        className="bg-secondary/40 h-[320px] w-full animate-pulse rounded-xl"
        aria-hidden
      />
    ),
  },
);

export function SpectrumHero() {
  return (
    <SpectrumChart
      mode="trace"
      wavenumbers={HERO_WAVENUMBERS}
      intensities={HERO_INTENSITIES}
      markers={HERO_MARKERS}
      height={320}
      // Pin the axis to the data range; the default starts at 0 and leaves a
      // stretch of dead space to the left of the first point.
      display={{
        showGrid: false,
        showLegend: false,
        lineWidth: 2,
        xMin: 250,
        xMax: 1750,
      }}
      ariaLabel="Raman spectrum of acetaminophen powder measured at 785 nm, with bands marked at 390, 858 and 1236 wavenumbers"
    />
  );
}
