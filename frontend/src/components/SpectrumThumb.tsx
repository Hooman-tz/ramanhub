import { API_BASE_URL } from '../api/client';

interface Props {
  spectrumId: string;
  /** Alt text should describe the spectrum, not the picture — screen-reader
   * users get nothing from "a line chart". */
  label?: string | null;
  peaks?: boolean;
  className?: string;
}

/** A small spectrum preview, rendered as an SVG by the server.
 *
 * A plain `<img>` rather than a chart component, deliberately: a profile or a
 * collection grid shows tens of these at once, and mounting tens of ECharts
 * instances (plus tens of JSON fetches) to draw a 240px squiggle is a lot of
 * work for a thumbnail. The server sends a few hundred bytes of path data
 * that the browser caches and revalidates with an ETag.
 *
 * `use-credentials` is required rather than optional: the API is on a
 * different origin in production, and without it the browser omits the
 * session cookie, so an owner's own draft tiles would 404 while every
 * published one worked — a confusing, partial failure.
 *
 * Colour comes from CSS. The SVG paints in `currentColor`, so dark mode and
 * any per-material tint work without the server rendering a second variant. */
export default function SpectrumThumb({ spectrumId, label, peaks = true, className }: Props) {
  const src = `${API_BASE_URL}/spectra/${spectrumId}/thumbnail.svg?peaks=${peaks}`;
  return (
    <img
      src={src}
      alt={label ? `Spectrum preview: ${label}` : 'Spectrum preview'}
      className={className ? `spectrum-thumb ${className}` : 'spectrum-thumb'}
      loading="lazy"
      decoding="async"
      crossOrigin="use-credentials"
      width={240}
      height={72}
    />
  );
}
