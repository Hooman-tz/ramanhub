import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getSpectrum, type Spectrum } from '../api/client';
import { getSpectrumData, type SpectrumData } from '../api/visualization';
import { runHca, runPca, type HcaResult, type PcaResult } from '../api/analysis';
import OverlayChart from '../components/OverlayChart';
import PcaPanel from '../components/PcaPanel';
import { useToast } from '../components/Toast';
import { Button, Card, EmptyState, Skeleton } from '../components/ui';

type Tab = 'overlay' | 'pca' | 'hca';

interface Loaded {
  spectrum: Spectrum;
  data: SpectrumData;
}

/** Multi-spectrum comparison: overlay, PCA and clustering over an arbitrary
 * selection, driven entirely by `?ids=` so a comparison is a shareable URL. */
export default function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { notify } = useToast();

  const ids = (searchParams.get('ids') ?? '').split(',').filter(Boolean);
  const [loaded, setLoaded] = useState<Loaded[]>([]);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<Tab>('overlay');
  const [pca, setPca] = useState<PcaResult | null>(null);
  const [hca, setHca] = useState<HcaResult | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (ids.length === 0) {
      setLoaded([]);
      return;
    }
    setLoading(true);
    Promise.all(
      ids.map(async (id) => ({
        spectrum: await getSpectrum(id),
        data: await getSpectrumData(id),
      })),
    )
      .then(setLoaded)
      .catch((err) => notify(err instanceof Error ? err.message : String(err), 'error'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams.get('ids')]);

  const label = useCallback(
    (item: Loaded, index: number) =>
      item.spectrum.title ?? item.spectrum.accession ?? `Spectrum ${index + 1}`,
    [],
  );

  function remove(id: string) {
    const next = ids.filter((existing) => existing !== id);
    const params = new URLSearchParams(searchParams);
    if (next.length) params.set('ids', next.join(','));
    else params.delete('ids');
    setSearchParams(params, { replace: true });
    // Any previous analysis described a different set of spectra; keeping it
    // on screen would mislabel it.
    setPca(null);
    setHca(null);
  }

  async function run(kind: 'pca' | 'hca') {
    setRunning(true);
    setAnalysisError(null);
    try {
      if (kind === 'pca') {
        setPca(await runPca({ spectrum_ids: ids, n_components: 3 }));
      } else {
        setHca(await runHca({ spectrum_ids: ids, n_clusters: Math.min(3, ids.length) }));
      }
    } catch (err) {
      setAnalysisError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  if (ids.length === 0) {
    return (
      <div>
        <h1>Compare</h1>
        <EmptyState title="Nothing selected">
          <p className="hint">
            Pick spectra from <Link to="/search">Search</Link> or your{' '}
            <Link to="/library">Library</Link> and choose “Compare selected”. Two or more
            are needed for PCA or clustering.
          </p>
        </EmptyState>
      </div>
    );
  }

  const enoughForMultivariate = ids.length >= 2;

  return (
    <div className="compare">
      <header className="page-head">
        <div>
          <h1>Compare {ids.length} spectra</h1>
          <p className="hint">
            This view is a shareable link — copy the URL to hand someone the exact
            comparison.
          </p>
        </div>
      </header>

      <div className="chips">
        {loaded.map((item, index) => (
          <span key={item.spectrum.id} className="chip chip--removable">
            <Link to={`/spectra/${item.spectrum.id}`}>{label(item, index)}</Link>
            <button
              type="button"
              onClick={() => remove(item.spectrum.id)}
              aria-label={`Remove ${label(item, index)} from the comparison`}
            >
              ×
            </button>
          </span>
        ))}
      </div>

      <div className="segmented" role="group" aria-label="Comparison view">
        {(['overlay', 'pca', 'hca'] as Tab[]).map((option) => (
          <button
            key={option}
            type="button"
            className="segmented__option"
            aria-pressed={tab === option}
            onClick={() => setTab(option)}
          >
            {option === 'overlay' ? 'Overlay' : option.toUpperCase()}
          </button>
        ))}
      </div>

      {loading && <Skeleton height="400px" />}

      {!loading && tab === 'overlay' && loaded.length > 0 && (
        <Card className="chart-panel">
          <OverlayChart
            series={loaded.map((item, index) => ({
              name: label(item, index),
              wavenumbers: item.data.wavenumbers,
              intensities: item.data.intensities,
            }))}
          />
        </Card>
      )}

      {!loading && tab === 'pca' && (
        <Card>
          {!enoughForMultivariate ? (
            <p className="hint">PCA needs at least two spectra.</p>
          ) : (
            <>
              <Button variant="primary" onClick={() => run('pca')} loading={running}>
                {pca ? 'Re-run PCA' : 'Run PCA'}
              </Button>
              {analysisError && <p className="error">{analysisError}</p>}
              {pca && (
                <PcaPanel
                  result={pca}
                  labels={pca.spectrum_ids.map((id) => {
                    const index = loaded.findIndex((l) => l.spectrum.id === id);
                    return index >= 0 ? label(loaded[index], index) : id;
                  })}
                />
              )}
            </>
          )}
        </Card>
      )}

      {!loading && tab === 'hca' && (
        <Card>
          {!enoughForMultivariate ? (
            <p className="hint">Clustering needs at least two spectra.</p>
          ) : (
            <>
              <Button variant="primary" onClick={() => run('hca')} loading={running}>
                {hca ? 'Re-run clustering' : 'Run clustering'}
              </Button>
              {analysisError && <p className="error">{analysisError}</p>}
              {hca?.labels && (
                <ul className="hca__clusters">
                  {hca.spectrum_ids.map((id, index) => {
                    const position = loaded.findIndex((l) => l.spectrum.id === id);
                    return (
                      <li key={id}>
                        <span
                          className={`cluster-dot cluster-dot--${hca.labels![index]}`}
                          aria-hidden="true"
                        />
                        <span>{position >= 0 ? label(loaded[position], position) : id}</span>
                        <span className="hint">cluster {hca.labels![index]}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </Card>
      )}
    </div>
  );
}
