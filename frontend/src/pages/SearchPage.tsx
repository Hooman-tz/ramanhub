import { useState } from 'react';
import { Link } from 'react-router-dom';
import { searchSpectra, type SpectrumSearchResult, type TrustTier } from '../api/search';

/** Functional, not polished: a filter form over the core objective-metadata
 * search (`GET /search/spectra`) plus a results table linking each row to
 * `/spectra/:id`. Deliberately has no sort-by-votes/popularity control —
 * results are always ordered by `published_at desc` server-side, per the
 * "search stays quarantined from social signals" requirement. */
export default function SearchPage() {
  const [materialType, setMaterialType] = useState('');
  const [excitationWavelengthNm, setExcitationWavelengthNm] = useState('');
  const [minSnr, setMinSnr] = useState('');
  const [trustTier, setTrustTier] = useState<TrustTier | ''>('');

  const [results, setResults] = useState<SpectrumSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const rows = await searchSpectra({
        material_type: materialType || undefined,
        excitation_wavelength_nm: excitationWavelengthNm ? Number(excitationWavelengthNm) : undefined,
        min_snr: minSnr ? Number(minSnr) : undefined,
        trust_tier: trustTier || undefined,
      });
      setResults(rows);
      setSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h1>Search</h1>

      <form onSubmit={handleSearch}>
        <div className="field-row">
          <label htmlFor="search-material-type">Material type</label>
          <input
            id="search-material-type"
            value={materialType}
            onChange={(e) => setMaterialType(e.target.value)}
            placeholder="e.g. quartz"
          />
        </div>
        <div className="field-row">
          <label htmlFor="search-excitation">Excitation wavelength (nm)</label>
          <input
            id="search-excitation"
            type="number"
            value={excitationWavelengthNm}
            onChange={(e) => setExcitationWavelengthNm(e.target.value)}
            placeholder="e.g. 532"
          />
        </div>
        <div className="field-row">
          <label htmlFor="search-min-snr">Min SNR</label>
          <input
            id="search-min-snr"
            type="number"
            value={minSnr}
            onChange={(e) => setMinSnr(e.target.value)}
          />
        </div>
        <div className="field-row">
          <label htmlFor="search-trust-tier">Trust tier</label>
          <select
            id="search-trust-tier"
            value={trustTier}
            onChange={(e) => setTrustTier(e.target.value as TrustTier | '')}
          >
            <option value="">Any</option>
            <option value="doi_verified">DOI-verified</option>
            <option value="community">Community</option>
          </select>
        </div>
        <button type="submit" disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {searched && !loading && results.length === 0 && <p>No results.</p>}

      {results.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Material type</th>
              <th>Excitation (nm)</th>
              <th>SNR</th>
              <th>Modality</th>
              <th>Trust tier</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>
            {results.map((row) => (
              <tr key={row.id}>
                <td>
                  <Link to={`/spectra/${row.id}`}>{row.title ?? row.id}</Link>
                </td>
                <td>{row.material_type ?? '—'}</td>
                <td>{row.excitation_wavelength_nm ?? '—'}</td>
                <td>{row.snr !== null && row.snr !== undefined ? row.snr.toFixed(2) : '—'}</td>
                <td>{row.modality}</td>
                <td>{row.doi ? 'DOI-verified' : 'Community'}</td>
                <td>{row.published_at ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
