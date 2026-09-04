import { ImageResponse } from "next/og";

import {
  HERO_INTENSITIES,
  HERO_WAVENUMBERS,
} from "~/components/marketing/hero-spectrum-data";

/**
 * The default social card for every route that does not override it. The root
 * layout has declared `twitter: { card: "summary_large_image" }` for a while
 * with no image behind it, so shared links rendered a blank card; this fills it
 * in site-wide rather than only for the landing page.
 *
 * Built from the same real acetaminophen trace the landing hero uses, drawn as
 * a data-URI SVG (satori handles `<img>` more predictably than inline SVG
 * children). No `next/font` — this runs at build time and should stay
 * dependency-free.
 */
export const alt =
  "Spectra Insight — an open commons for spectral data, Raman first";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const TEAL = "#0d6b6e";
const CREAM = "#faf8f5";

/** The trace as an SVG polyline, scaled into a 1200x260 box. */
function tracePoints(): string {
  const xs = HERO_WAVENUMBERS;
  const ys = HERO_INTENSITIES;
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);

  return xs
    .map((x, i) => {
      const y = ys[i] ?? yMin;
      const px = ((x - xMin) / (xMax - xMin)) * 1200;
      // SVG y grows downward, so invert; inset 10px top and bottom.
      const py = 250 - ((y - yMin) / (yMax - yMin)) * 240;
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
}

export default function OpengraphImage() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="260" viewBox="0 0 1200 260"><polyline points="${tracePoints()}" fill="none" stroke="${TEAL}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  const src = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: CREAM,
          padding: "64px 64px 0",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 12,
                background: TEAL,
              }}
            />
            <div style={{ fontSize: 34, fontWeight: 700, color: "#1c1917" }}>
              Spectra Insight
            </div>
          </div>

          <div
            style={{
              marginTop: 40,
              fontSize: 62,
              fontWeight: 700,
              lineHeight: 1.1,
              letterSpacing: "-0.02em",
              color: "#1c1917",
              maxWidth: 900,
            }}
          >
            An open commons for spectral data
          </div>

          <div
            style={{
              marginTop: 22,
              fontSize: 30,
              color: "#79716b",
              maxWidth: 880,
            }}
          >
            Share your spectra, ask the questions a manual cannot answer, and
            publish records people can actually reuse.
          </div>
        </div>

        <img src={src} width={1200} height={260} alt="" />
      </div>
    ),
    size,
  );
}
