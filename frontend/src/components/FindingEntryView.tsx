import { useEffect, useState } from 'react';
import { runHca, runPca, type HcaResult, type PcaResult } from '../api/analysis';
import { getSpectrumData, type SpectrumData } from '../api/visualization';
import type { FindingEntry, MemberSpectrum } from '../api/findings';
import OverlayChart from './OverlayChart';
import PcaPanel from './PcaPanel';
import { Skeleton } from './ui';

/** Renders one post in a Finding thread.
 *
 * Analysis entries recompute from the parameters recorded in `config`
 * rather than displaying a stored image. That costs a request per view and
 * buys the thing that matters on a reproducibility platform: the figure
 * always reflects the data as it is now, and a reader can re-run it with
 * the same parameters and get the same answer. A stored PNG would silently
 * keep showing a result that its underlying spectra no longer support. */
export default function FindingEntryView({
  entry,
  members,
}: {
  entry: FindingEntry;
  members: MemberSpectrum[];
}) {
  const [pca, setPca] = useState<PcaResult | null>(null);
  const [hca, setHca] = useState<HcaResult | null>(null);
  const [series, setSeries] = useState<SpectrumData[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = entry.config ?? {};
  const configIds = Array.isArray(config.spectrum_ids)
    ? (config.spectrum_ids as string[])
    : members.map((m) => m.spectrum_id);

  function labelFor(id: string, index: number): string {
    const member = members.find((m) => m.spectrum_id === id);
    return member?.label ?? member?.title ?? member?.accession ?? `Spectrum ${index + 1}`;
  }

  useEffect(() => {
    let cancelled = false;
    setError(null);

    async function load() {
      if (entry.kind === 'pca') {
        setLoading(true);
        try {
          const result = await runPca({
            spectrum_ids: configIds,
            n_components: (config.n_components as number) ?? 3,
            mean_center: (config.mean_center as boolean) ?? true,
            scale: (config.scale as boolean) ?? false,
          });
          if (!cancelled) setPca(result);
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        } finally {
          if (!cancelled) setLoading(false);
        }
      } else if (entry.kind === 'hca') {
        setLoading(true);
        try {
          const result = await runHca({
            spectrum_ids: configIds,
            metric: (config.metric as string) ?? 'correlation',
            method: (config.method as string) ?? 'average',
            n_clusters: (config.n_clusters as number) ?? null,
          });
          if (!cancelled) setHca(result);
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        } finally {
          if (!cancelled) setLoading(false);
        }
      } else if (entry.kind === 'spectra' || entry.kind === 'figure') {
        setLoading(true);
        try {
          const loaded = await Promise.all(configIds.map((id) => getSpectrumData(id)));
          if (!cancelled) setSeries(loaded);
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        } finally {
          if (!cancelled) setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.id, entry.kind, JSON.stringify(entry.config)]);

  return (
    <article className="entry">
      <div className="entry__kind">{entry.kind}</div>

      {entry.body_md && <p className="entry__body">{entry.body_md}</p>}

      {error && <p className="error">{error}</p>}
      {loading && <Skeleton height="220px" />}

      {entry.kind === 'pca' && pca && (
        <PcaPanel
          result={pca}
          labels={pca.spectrum_ids.map(labelFor)}
          groups={pca.spectrum_ids.map((id) => {
            // Group by the member label with any trailing "— replicate N"
            // stripped, so replicates of one material share a color. This
            // is a display convenience only; nothing is inferred from it.
            const label = labelFor(id, 0);
            return label.split('—')[0].trim();
          })}
        />
      )}

      {entry.kind === 'hca' && hca && (
        <div className="hca">
          <p className="hint">
            {hca.n_spectra} spectra, {(config.metric as string) ?? 'correlation'} distance,{' '}
            {(config.method as string) ?? 'average'} linkage.
          </p>
          {hca.labels && (
            <ul className="hca__clusters">
              {hca.spectrum_ids.map((id, index) => (
                <li key={id}>
                  <span className={`cluster-dot cluster-dot--${hca.labels![index]}`} aria-hidden="true" />
                  <span>{labelFor(id, index)}</span>
                  <span className="hint">cluster {hca.labels![index]}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {(entry.kind === 'spectra' || entry.kind === 'figure') && series && (
        <OverlayChart
          height={360}
          series={series.map((data, index) => ({
            name: labelFor(configIds[index], index),
            wavenumbers: data.wavenumbers,
            intensities: data.intensities,
          }))}
        />
      )}

      {entry.kind === 'peaks' && (
        <p className="hint">
          Peak parameters recorded:{' '}
          <code>{JSON.stringify(entry.config ?? {})}</code>
        </p>
      )}
    </article>
  );
}
