import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getMyLibrary, type SpectrumSearchResult } from '../api/search';
import { spectrumDownloadUrl } from '../api/exports';
import SpectrumTable from '../components/SpectrumTable';
import { useToast } from '../components/Toast';
import { Button, Card, EmptyState, Skeleton } from '../components/ui';

type StateFilter = 'all' | 'draft' | 'published' | 'embargoed';

/** The personal database: everything the signed-in user owns, in every
 * state, with the bulk actions that make a collection workable rather than
 * just listable. Distinct from `/search`, which is the public commons and
 * shows published work only. */
export default function LibraryPage() {
  const navigate = useNavigate();
  const { notify } = useToast();

  const [rows, setRows] = useState<SpectrumSearchResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const [query, setQuery] = useState('');
  const [stateFilter, setStateFilter] = useState<StateFilter>('all');

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    getMyLibrary()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(refresh, [refresh]);

  // Filtering happens client-side because the library is one user's own
  // collection — hundreds of rows, not the whole commons. That keeps typing
  // in the search box instant instead of firing a request per keystroke.
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (stateFilter !== 'all' && row.state !== stateFilter) return false;
      if (!needle) return true;
      return [row.title, row.material_type, row.accession]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle));
    });
  }, [rows, query, stateFilter]);

  const stats = useMemo(() => {
    const counts = { total: rows.length, draft: 0, published: 0, embargoed: 0 };
    for (const row of rows) {
      if (row.state === 'draft') counts.draft += 1;
      else if (row.state === 'published') counts.published += 1;
      else if (row.state === 'embargoed') counts.embargoed += 1;
    }
    return counts;
  }, [rows]);

  const selectedIds = [...selected];

  function compareSelected() {
    if (selectedIds.length < 2) {
      notify('Pick at least two spectra to compare.', 'error');
      return;
    }
    navigate(`/compare?ids=${selectedIds.join(',')}`);
  }

  function downloadSelected() {
    // One navigation per file rather than a client-side zip: the browser
    // streams each straight to disk with the server's filename, and there's
    // no memory ceiling on how much can be downloaded at once.
    selectedIds.forEach((id, index) => {
      // Stagger slightly — browsers drop rapid-fire programmatic downloads.
      setTimeout(() => {
        const link = document.createElement('a');
        link.href = spectrumDownloadUrl(id, 'csv', 'processed');
        link.download = '';
        document.body.appendChild(link);
        link.click();
        link.remove();
      }, index * 300);
    });
    notify(`Downloading ${selectedIds.length} spectra…`, 'success');
  }

  return (
    <div className="library">
      <header className="page-head">
        <div>
          <h1>My library</h1>
          <p className="hint">
            Everything you own, in every state. Drafts are private to you — publishing is
            what puts a spectrum into the <Link to="/search">public commons</Link>.
          </p>
        </div>
        <Link to="/upload" className="ui-button ui-button--primary">
          Upload spectra
        </Link>
      </header>

      <Card>
        <dl className="stat-row">
          <div>
            <dt>Total</dt>
            <dd>{stats.total}</dd>
          </div>
          <div>
            <dt>Drafts</dt>
            <dd>{stats.draft}</dd>
          </div>
          <div>
            <dt>Published</dt>
            <dd>{stats.published}</dd>
          </div>
          <div>
            <dt>Embargoed</dt>
            <dd>{stats.embargoed}</dd>
          </div>
        </dl>
      </Card>

      <div className="filter-bar">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by title, material or accession…"
          aria-label="Filter your library"
          className="library__search"
        />

        <div className="segmented" role="group" aria-label="State">
          {(['all', 'draft', 'published', 'embargoed'] as StateFilter[]).map((option) => (
            <button
              key={option}
              type="button"
              className="segmented__option"
              aria-pressed={stateFilter === option}
              onClick={() => setStateFilter(option)}
            >
              {option[0].toUpperCase() + option.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* A persistent action bar, shown only when there's a selection —
          the pattern every file manager uses, so bulk actions are
          discoverable without cluttering the default view. */}
      {selected.size > 0 && (
        <div className="selection-bar">
          <span>
            {selected.size} selected
          </span>
          <Button size="sm" onClick={compareSelected}>
            Compare
          </Button>
          <Button size="sm" onClick={downloadSelected}>
            Download CSV
          </Button>
          <Link
            to={`/findings/new`}
            className="ui-button ui-button--sm"
            title="Start a finding, then attach these spectra to it"
          >
            Write a finding
          </Link>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {loading ? (
        <Skeleton lines={6} height="2rem" />
      ) : rows.length === 0 ? (
        <EmptyState title="Your library is empty">
          <p className="hint">
            <Link to="/upload">Upload a spectrum</Link> to get started — you can process it
            without an account, and publish it when you're ready.
          </p>
        </EmptyState>
      ) : filtered.length === 0 ? (
        <EmptyState title="Nothing matches those filters">
          <p className="hint">Try clearing the search box or switching back to “All”.</p>
        </EmptyState>
      ) : (
        <SpectrumTable rows={filtered} selected={selected} onSelectedChange={setSelected} />
      )}
    </div>
  );
}
