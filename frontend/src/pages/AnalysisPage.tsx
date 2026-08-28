import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import {
  cancelAnalysisRun,
  createAnalysisDataset,
  createAnalysisRun,
  getAnalysisRun,
  type AnalysisRun,
} from '../api/analysis';
import { getMyLibrary, searchSpectra, type SpectrumSearchResult } from '../api/search';
import { Button, Card, Skeleton } from '../components/ui';

function labelFor(row: SpectrumSearchResult): string {
  return row.title ?? `Spectrum ${row.id.slice(0, 8)}`;
}

export default function AnalysisPage() {
  const { user, loading: authLoading } = useAuth();
  const [library, setLibrary] = useState<SpectrumSearchResult[]>([]);
  const [publicMatches, setPublicMatches] = useState<SpectrumSearchResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [datasetName, setDatasetName] = useState('Exploration set');
  const [search, setSearch] = useState('');
  const [analysisType, setAnalysisType] = useState<'pca' | 'pca_kmeans'>('pca');
  const [components, setComponents] = useState(2);
  const [clusters, setClusters] = useState(2);
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      setLoading(false);
      return;
    }
    getMyLibrary({ modality: 'raman' })
      .then(setLibrary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [authLoading, user]);

  useEffect(() => {
    if (!run || !['pending', 'running'].includes(run.status)) return;
    const timer = window.setInterval(() => {
      getAnalysisRun(run.id).then(setRun).catch((err) => setError(String(err)));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [run]);

  const candidates = useMemo(() => {
    const byId = new Map<string, SpectrumSearchResult>();
    [...library, ...publicMatches].forEach((item) => byId.set(item.id, item));
    return [...byId.values()];
  }, [library, publicMatches]);

  function toggleSpectrum(id: string) {
    setSelectedIds((current) => (
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id]
    ));
  }

  async function findPublic() {
    setError(null);
    try {
      setPublicMatches(await searchSpectra({ material_type: search || undefined, modality: 'raman', limit: 20 }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function startRun() {
    if (selectedIds.length < 2) {
      setError('Choose at least two Raman spectra for an exploration.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const dataset = await createAnalysisDataset({ name: datasetName, spectrum_ids: selectedIds });
      const nextRun = await createAnalysisRun(dataset.id, {
        analysis_type: analysisType,
        components,
        grid_points: 128,
        ...(analysisType === 'pca_kmeans' ? { clusters } : {}),
        execution_backend: 'local',
      });
      setRun(nextRun);
    } catch (err) {
      setError(
        err instanceof Error && err.message.includes('already exists')
          ? 'That saved selection name belongs to a different dataset. Rename it or reuse the original selection.'
          : err instanceof Error ? err.message : String(err),
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || authLoading) return <Skeleton lines={6} height="2.5rem" />;
  if (!user) {
    return (
      <div className="page-stack">
        <header className="page-header">
          <p className="eyebrow">Reproducible exploration</p>
          <h1>Explore a Raman dataset</h1>
        </header>
        <Card title="Sign in to start an analysis">
          <p className="hint">Save a private/public spectrum selection and run reproducible PCA locally at no charge.</p>
          <Link to="/login">Sign in to explore spectra</Link>
        </Card>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Reproducible exploration</p>
        <h1>Explore a Raman dataset</h1>
        <p className="hint">
          Select private spectra you own and visible public spectra. Every run saves its immutable inputs,
          processing provenance, software versions, quality checks, and output hash.
        </p>
      </header>

      <Card title="1. Choose spectra">
        <div className="field-row">
          <label htmlFor="analysis-public-search">Find public Raman spectra</label>
          <div className="inline-actions">
            <input id="analysis-public-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Material, e.g. quartz" />
            <Button variant="glass" onClick={findPublic}>Search public</Button>
          </div>
        </div>
        <p className="hint">{selectedIds.length} of up to 100 spectra selected. Cross-modality selections are blocked.</p>
        <div className="data-table-wrap">
          <table className="data-table">
            <thead><tr><th>Use</th><th>Spectrum</th><th>Source</th><th>State</th></tr></thead>
            <tbody>
              {candidates.map((row) => (
                <tr key={row.id}>
                  <td><input type="checkbox" checked={selectedIds.includes(row.id)} onChange={() => toggleSpectrum(row.id)} aria-label={`Select ${labelFor(row)}`} /></td>
                  <td><Link to={`/spectra/${row.id}`}>{labelFor(row)}</Link></td>
                  <td>{library.some((item) => item.id === row.id) ? 'My library' : 'Public commons'}</td>
                  <td>{row.state}</td>
                </tr>
              ))}
              {candidates.length === 0 && <tr><td colSpan={4}>Your library is empty. Upload spectra or search the public commons.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="2. Run analysis">
        <div className="field-row">
          <label htmlFor="analysis-dataset-name">Saved selection name</label>
          <input id="analysis-dataset-name" value={datasetName} onChange={(event) => setDatasetName(event.target.value)} />
        </div>
        <div className="field-row">
          <label htmlFor="analysis-type">Method</label>
          <select id="analysis-type" value={analysisType} onChange={(event) => setAnalysisType(event.target.value as 'pca' | 'pca_kmeans')}>
            <option value="pca">Principal component analysis (PCA)</option>
            <option value="pca_kmeans">PCA with deterministic k-means clusters</option>
          </select>
        </div>
        <div className="field-row">
          <label htmlFor="analysis-components">Components</label>
          <input id="analysis-components" type="number" min={1} max={10} value={components} onChange={(event) => setComponents(Number(event.target.value))} />
        </div>
        {analysisType === 'pca_kmeans' && (
          <div className="field-row">
            <label htmlFor="analysis-clusters">Clusters</label>
            <input id="analysis-clusters" type="number" min={2} max={8} value={clusters} onChange={(event) => setClusters(Number(event.target.value))} />
          </div>
        )}
        <p className="hint">Runs execute locally at no charge. Hosted execution is intentionally unavailable until quotas, isolation, metering, and subscription controls are configured.</p>
        <Button onClick={startRun} loading={submitting} disabled={selectedIds.length < 2}>Run locally</Button>
      </Card>

      {error && <p className="error">{error}</p>}
      {run && (
        <Card title="Analysis run">
          <p><strong>Status:</strong> {run.status} · <strong>Attempt:</strong> {run.attempt_count}/{run.max_attempts}</p>
          {['pending', 'running'].includes(run.status) && <Button variant="danger" onClick={() => cancelAnalysisRun(run.id).then(setRun)}>Cancel run</Button>}
          {run.error_message && <p className="error">{run.error_message}</p>}
          {run.output && (
            <>
              <p><strong>Explained variance:</strong> {run.output.explained_variance_ratio.map((value) => `${(value * 100).toFixed(1)}%`).join(', ')}</p>
              <p><strong>Output hash:</strong> <code>{run.output_hash}</code></p>
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead><tr><th>Spectrum</th><th>PC1</th><th>PC2</th><th>Cluster</th></tr></thead>
                  <tbody>
                    {run.output.spectrum_ids.map((id, index) => (
                      <tr key={id}><td>{id.slice(0, 8)}</td><td>{run.output?.scores[index]?.[0]?.toFixed(4) ?? '—'}</td><td>{run.output?.scores[index]?.[1]?.toFixed(4) ?? '—'}</td><td>{run.output?.cluster_labels?.[index] ?? '—'}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  );
}