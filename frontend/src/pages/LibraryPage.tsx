import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getMyLibrary, type SpectrumSearchResult } from '../api/search';

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
    <div>
      <h1>My library</h1>

      <form onSubmit={refresh}>
        <div className="field-row">
          <label htmlFor="library-material-type">Material type</label>
          <input
            id="library-material-type"
            value={materialType}
            onChange={(e) => setMaterialType(e.target.value)}
            placeholder="e.g. quartz"
          />
        </div>
        <div className="field-row">
          <label htmlFor="library-excitation">Excitation wavelength (nm)</label>
          <input
            id="library-excitation"
            type="number"
            value={excitationWavelengthNm}
            onChange={(e) => setExcitationWavelengthNm(e.target.value)}
          />
        </div>
        <div className="field-row">
          <label htmlFor="library-min-snr">Min SNR</label>
          <input
            id="library-min-snr"
            type="number"
            value={minSnr}
            onChange={(e) => setMinSnr(e.target.value)}
          />
        </div>
        <button type="submit" disabled={loading}>
          {loading ? 'Loading...' : 'Filter'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}
      {loading && <p>Loading library...</p>}
      {!loading && results.length === 0 && <p>Nothing in your library yet.</p>}

      {results.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>State</th>
              <th>Material type</th>
              <th>Excitation (nm)</th>
              <th>SNR</th>
              <th>Modality</th>
            </tr>
          </thead>
          <tbody>
            {results.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link to={`/spectra/${row.id}`}>{row.title ?? row.id}</Link>
                </td>
                <td>
                  <span className={`badge badge-${row.state}`}>{row.state}</span>
                </td>
                <td>{row.material_type ?? '—'}</td>
                <td>{row.excitation_wavelength_nm ?? '—'}</td>
                <td>{row.snr !== null && row.snr !== undefined ? row.snr.toFixed(2) : '—'}</td>
                <td>{row.modality}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
