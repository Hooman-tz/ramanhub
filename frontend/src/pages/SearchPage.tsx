import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  searchSpectra,
  type SearchSort,
  type SpectrumSearchResult,
  type TrustTier,
} from '../api/search';
import SpectrumTable from '../components/SpectrumTable';
import { useToast } from '../components/Toast';
import { Button, Card, EmptyState, Skeleton } from '../components/ui';

const SORTS: Array<{ value: SearchSort; label: string; hint: string }> = [
  {
    value: 'relevance',
    label: 'Relevance',
    hint: 'Blends community engagement, recency and peer-reviewed status.',
  },
  {
    value: 'newest',
    label: 'Newest',
    hint: 'Most recently published first. Engagement is ignored entirely.',
  },
  {
    value: 'engagement',
    label: 'Most discussed',
    hint: 'Time-decayed upvotes — what people are actually looking at.',
  },
  {
    value: 'snr',
    label: 'Best quality',
    hint: 'Highest measured signal-to-noise first. Purely objective.',
  },
];

/** The central public database. Published spectra only — a contributor's
 * drafts live in their own `/library` and never surface here. */
export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { notify } = useToast();

  const [results, setResults] = useState<SpectrumSearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Filters live in the URL so a search is a shareable link — the same
  // reasoning as the compare view.
  const materialType = searchParams.get('material_type') ?? '';
  const excitation = searchParams.get('excitation_wavelength_nm') ?? '';
  const minSnr = searchParams.get('min_snr') ?? '';
  const trustTier = (searchParams.get('trust_tier') as TrustTier | null) ?? null;
  const sort = (searchParams.get('sort') as SearchSort | null) ?? 'relevance';

  const [materialDraft, setMaterialDraft] = useState(materialType);

  const runSearch = useCallback(() => {
    setLoading(true);
    setError(null);
    searchSpectra({
      material_type: materialType || undefined,
      excitation_wavelength_nm: excitation ? Number(excitation) : undefined,
      min_snr: minSnr ? Number(minSnr) : undefined,
      trust_tier: trustTier ?? undefined,
      sort,
      limit: 50,
    })
      .then(setResults)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [materialType, excitation, minSnr, trustTier, sort]);

  useEffect(runSearch, [runSearch]);

  function setParam(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  }

  const activeSort = useMemo(() => SORTS.find((s) => s.value === sort), [sort]);
  const selectedIds = [...selected];

  function compareSelected() {
    if (selectedIds.length < 2) {
      notify('Pick at least two spectra to compare.', 'error');
      return;
    }
    navigate(`/compare?ids=${selectedIds.join(',')}`);
  }

  return (
    <div className="search-page">
      <header className="page-head">
        <div>
          <h1>Search the commons</h1>
          <p className="hint">
            Every published spectrum on RamanHub. Browsing rather than looking for
            something specific? Try the <Link to="/feed">feed</Link>.
          </p>
        </div>
      </header>

      <Card>
        <form
          className="search-facets"
          onSubmit={(e) => {
            e.preventDefault();
            setParam('material_type', materialDraft || null);
          }}
        >
          <label className="field">
            <span>Material</span>
            <input
              value={materialDraft}
              onChange={(e) => setMaterialDraft(e.target.value)}
              placeholder="quartz, cellulose, R6G…"
            />
          </label>

          <label className="field">
            <span>Laser (nm)</span>
            <input
              type="number"
              value={excitation}
              onChange={(e) => setParam('excitation_wavelength_nm', e.target.value || null)}
              placeholder="785"
            />
          </label>

          <label className="field">
            <span>Minimum SNR</span>
            <input
              type="number"
              value={minSnr}
              onChange={(e) => setParam('min_snr', e.target.value || null)}
              placeholder="10"
            />
          </label>

          <Button type="submit" variant="primary">
            Search
          </Button>
        </form>
      </Card>

      <div className="filter-bar">
        <label className="inline-field">
          <span>Sort</span>
          <select value={sort} onChange={(e) => setParam('sort', e.target.value)}>
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <div className="segmented" role="group" aria-label="Trust tier">
          <button
            type="button"
            className="segmented__option"
            aria-pressed={trustTier === null}
            onClick={() => setParam('trust_tier', null)}
          >
            All
          </button>
          <button
            type="button"
            className="segmented__option"
            aria-pressed={trustTier === 'doi_verified'}
            onClick={() => setParam('trust_tier', 'doi_verified')}
          >
            DOI-verified
          </button>
          <button
            type="button"
            className="segmented__option"
            aria-pressed={trustTier === 'community'}
            onClick={() => setParam('trust_tier', 'community')}
          >
            Community
          </button>
        </div>

        {activeSort && <p className="hint">{activeSort.hint}</p>}
      </div>

      {selected.size > 0 && (
        <div className="selection-bar">
          <span>{selected.size} selected</span>
          <Button size="sm" onClick={compareSelected}>
            Compare
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {loading ? (
        <Skeleton lines={6} height="2rem" />
      ) : results.length === 0 ? (
        <EmptyState title="No spectra match">
          <p className="hint">
            Try widening the filters — or <Link to="/upload">contribute the first one</Link>.
          </p>
        </EmptyState>
      ) : (
        <>
          <p className="hint">{results.length} published spectra</p>
          <SpectrumTable
            rows={results}
            selected={selected}
            onSelectedChange={setSelected}
            showState={false}
          />
        </>
      )}
    </div>
  );
}
