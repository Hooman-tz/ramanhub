import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getMyLibrary, type SpectrumSearchResult } from '../api/search';
import { Button, EmptyState, InputField, Skeleton } from '../components/ui';

/** Functional, not polished: same filter pattern as `SearchPage`, scoped to
 * the current user's own private reference library (`GET /library/mine`) —
 * draft/published/embargoed spectra all visible here, unlike `/search`.
 * "Promotable into the public database" is just the existing publish flow
 * on `SpectrumViewPage`; each row links there rather than duplicating a
 * publish action on this page. */
export default function LibraryPage() {
  const [materialType, setMaterialType] = useState('');
  const [excitationWavelengthNm, setExcitationWavelengthNm] = useState('');
  const [minSnr, setMinSnr] = useState('');

  const [results, setResults] = useState<SpectrumSearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh(e?: React.FormEvent) {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const rows = await getMyLibrary({
        material_type: materialType || undefined,
        excitation_wavelength_nm: excitationWavelengthNm ? Number(excitationWavelengthNm) : undefined,
        min_snr: minSnr ? Number(minSnr) : undefined,
      });
      setResults(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="workspace-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Private workspace</p>
          <h1>Library</h1>
          <p className="page-intro">Your spectra, processing history, and publication readiness in one place.</p>
        </div>
        <Link to="/upload" className="ui-button ui-button--primary">Upload spectrum</Link>
      </header>

      <form onSubmit={refresh} className="surface filter-surface" aria-label="Filter library">
        <InputField
          id="library-material-type"
          label="Material"
          value={materialType}
          onChange={(e) => setMaterialType(e.target.value)}
          placeholder="e.g. quartz"
        />
        <InputField
          id="library-excitation"
          label="Excitation (nm)"
          type="number"
          value={excitationWavelengthNm}
          onChange={(e) => setExcitationWavelengthNm(e.target.value)}
          placeholder="532"
        />
        <InputField
          id="library-min-snr"
          label="Minimum SNR"
          type="number"
          value={minSnr}
          onChange={(e) => setMinSnr(e.target.value)}
          placeholder="—"
        />
        <Button type="submit" variant="glass" loading={loading}>Apply filters</Button>
      </form>

      {error && <p className="error">{error}</p>}
      {loading && <Skeleton lines={5} height="3rem" />}
      {!loading && results.length === 0 && (
        <EmptyState title="Your library is ready for its first spectrum">
          <p>Upload a raw file to begin a private, reproducible analysis.</p>
          <Link to="/upload" className="ui-button ui-button--primary">Upload a spectrum</Link>
        </EmptyState>
      )}

      {results.length > 0 && (
        <div className="data-table-wrap">
          <table className="data-table">
            <caption className="sr-only">Private spectrum library</caption>
            <thead>
              <tr>
                <th>Title</th><th>Visibility</th><th>Material</th><th>Excitation</th>
                <th>SNR</th><th>Readiness</th><th>Modality</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr key={row.id}>
                  <td><Link to={`/spectra/${row.id}`}>{row.title ?? 'Untitled spectrum'}</Link></td>
                  <td><span className={`badge badge-${row.state}`}><span className="status-dot" aria-hidden="true" />{row.state}</span></td>
                  <td>{row.material_type ?? '—'}</td>
                  <td>{row.excitation_wavelength_nm ?? '—'}{row.excitation_wavelength_nm ? ' nm' : ''}</td>
                  <td>{row.snr !== null && row.snr !== undefined ? row.snr.toFixed(2) : '—'}</td>
                  <td>
                    <span className={`badge badge-${row.qc_state === 'passed' ? 'published' : row.qc_state === 'blocked' ? 'embargoed' : 'draft'}`}>
                      {row.publish_ready ? 'Ready' : row.qc_state === 'blocked' ? 'Blocked' : 'Needs review'}
                    </span>
                  </td>
                  <td>{row.modality}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
