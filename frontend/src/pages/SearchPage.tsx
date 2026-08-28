import { useState } from 'react';
import { Link } from 'react-router-dom';
import { searchSpectra, type SpectrumSearchResult, type TrustTier } from '../api/search';
import { Button, EmptyState, InputField, SelectField, Skeleton } from '../components/ui';

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
    <div className="workspace-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Public reference data</p>
          <h1>Search spectra</h1>
          <p className="page-intro">Find published Raman data by objective metadata. Results are ordered by publication date, never social activity.</p>
        </div>
      </header>

      <form onSubmit={handleSearch} className="surface filter-surface" aria-label="Search published spectra">
        <InputField
          id="search-material-type"
          label="Material"
          value={materialType}
          onChange={(e) => setMaterialType(e.target.value)}
          placeholder="e.g. quartz"
        />
        <InputField
          id="search-excitation"
          label="Excitation (nm)"
          type="number"
          value={excitationWavelengthNm}
          onChange={(e) => setExcitationWavelengthNm(e.target.value)}
          placeholder="532"
        />
        <InputField
          id="search-min-snr"
          label="Minimum SNR"
          type="number"
          value={minSnr}
          onChange={(e) => setMinSnr(e.target.value)}
          placeholder="—"
        />
        <SelectField
          id="search-trust-tier"
          label="Trust tier"
          value={trustTier}
          onChange={(e) => setTrustTier(e.target.value as TrustTier | '')}
        >
          <option value="">Any evidence</option>
          <option value="doi_verified">DOI verified</option>
          <option value="community">Community</option>
        </SelectField>
        <Button type="submit" variant="primary" loading={loading}>Search spectra</Button>
      </form>

      {error && <p className="error">{error}</p>}

      {loading && <Skeleton lines={4} height="3rem" />}
      {searched && !loading && results.length === 0 && (
        <EmptyState title="No spectra match those filters">
          <p>Try a broader material, wavelength, or trust tier.</p>
        </EmptyState>
      )}

      {results.length > 0 && (
        <div className="data-table-wrap"><table className="data-table">
          <thead>
            <tr>
              <th>Title</th>
                <th>Material</th>
                <th>Excitation</th>
              <th>SNR</th>
              <th>Modality</th>
                <th>Evidence</th>
              <th>Published</th>
            </tr>
          </thead>
          <tbody>
            {results.map((row) => (
              <tr key={row.id}>
                <td><Link to={`/spectra/${row.id}`}>{row.title ?? 'Untitled spectrum'}</Link></td>
                <td>{row.material_type ?? '—'}</td>
                <td>{row.excitation_wavelength_nm ?? '—'}{row.excitation_wavelength_nm ? ' nm' : ''}</td>
                <td>{row.snr !== null && row.snr !== undefined ? row.snr.toFixed(2) : '—'}</td>
                <td>{row.modality}</td>
                <td><span className={`badge ${row.doi ? 'published' : 'draft'}`}>{row.doi ? 'DOI linked' : 'Community'}</span></td>
                <td>{row.published_at ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </div>
  );
}
