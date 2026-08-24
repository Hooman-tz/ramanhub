import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { SpectrumSearchResult } from '../api/search';

export type SortKey = 'title' | 'material_type' | 'excitation_wavelength_nm' | 'snr' | 'published_at';

interface Props {
  rows: SpectrumSearchResult[];
  /** Selected spectrum ids. Controlled by the parent so a page can act on
   * the selection (compare, export, add to a finding). */
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  /** Hides the state column on surfaces where everything is published. */
  showState?: boolean;
}

const COLUMNS: Array<{ key: SortKey; label: string; numeric?: boolean }> = [
  { key: 'title', label: 'Spectrum' },
  { key: 'material_type', label: 'Material' },
  { key: 'excitation_wavelength_nm', label: 'Laser (nm)', numeric: true },
  { key: 'snr', label: 'SNR', numeric: true },
  { key: 'published_at', label: 'Published' },
];

function compare(a: SpectrumSearchResult, b: SpectrumSearchResult, key: SortKey): number {
  const av = a[key];
  const bv = b[key];
  // Missing values sort last in both directions — an unmeasured SNR is
  // never the most interesting row, ascending or descending.
  if (av === null || av === undefined) return 1;
  if (bv === null || bv === undefined) return -1;
  if (typeof av === 'number' && typeof bv === 'number') return av - bv;
  return String(av).localeCompare(String(bv));
}

/** Sortable, selectable table of spectra — the shared surface behind both
 * the personal library and the public commons, so the two behave
 * identically instead of drifting into two different tables. */
export default function SpectrumTable({
  rows,
  selected,
  onSelectedChange,
  showState = true,
}: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('published_at');
  const [descending, setDescending] = useState(true);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => (descending ? -compare(a, b, sortKey) : compare(a, b, sortKey)));
    return copy;
  }, [rows, sortKey, descending]);

  const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.id));
  // Distinct from "all": drives the header checkbox's indeterminate state,
  // which is what tells a user their selection is partial without them
  // having to count rows.
  const someSelected = rows.some((row) => selected.has(row.id));

  function toggleAll() {
    if (allSelected) {
      const next = new Set(selected);
      rows.forEach((row) => next.delete(row.id));
      onSelectedChange(next);
    } else {
      onSelectedChange(new Set([...selected, ...rows.map((row) => row.id)]));
    }
  }

  function toggleOne(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onSelectedChange(next);
  }

  function sortBy(key: SortKey) {
    if (key === sortKey) {
      setDescending((d) => !d);
    } else {
      setSortKey(key);
      // Dates and quality metrics read "best/newest first"; names read A-Z.
      setDescending(key === 'published_at' || key === 'snr');
    }
  }

  return (
    <div className="table-scroll">
      <table className="data-table data-table--rows">
        <thead>
          <tr>
            <th scope="col" className="data-table__check">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected && !allSelected;
                }}
                onChange={toggleAll}
                aria-label="Select all spectra on this page"
              />
            </th>
            {COLUMNS.map((column) => (
              <th key={column.key} scope="col">
                <button
                  type="button"
                  className="data-table__sort"
                  onClick={() => sortBy(column.key)}
                  aria-sort={
                    sortKey === column.key ? (descending ? 'descending' : 'ascending') : 'none'
                  }
                >
                  {column.label}
                  <span aria-hidden="true" className="data-table__caret">
                    {sortKey === column.key ? (descending ? '▾' : '▴') : ''}
                  </span>
                </button>
              </th>
            ))}
            {showState && <th scope="col">State</th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.id} className={selected.has(row.id) ? 'is-selected' : undefined}>
              <td className="data-table__check">
                <input
                  type="checkbox"
                  checked={selected.has(row.id)}
                  onChange={() => toggleOne(row.id)}
                  aria-label={`Select ${row.title ?? row.accession ?? 'spectrum'}`}
                />
              </td>
              <td>
                <Link to={`/spectra/${row.id}`}>{row.title ?? 'Untitled'}</Link>
                {row.accession && <code className="accession">{row.accession}</code>}
                {row.doi && <span className="chip chip--verified">DOI</span>}
              </td>
              <td>{row.material_type ?? '—'}</td>
              <td className="data-table__num">
                {row.excitation_wavelength_nm ?? '—'}
              </td>
              <td className="data-table__num">
                {row.snr != null ? Number(row.snr).toFixed(1) : '—'}
              </td>
              <td>
                {row.published_at
                  ? new Date(row.published_at).toLocaleDateString()
                  : '—'}
              </td>
              {showState && (
                <td>
                  <span className={`chip chip--${row.state === 'published' ? 'verified' : 'draft'}`}>
                    {row.state}
                  </span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
