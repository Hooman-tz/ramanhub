import { useMemo, useState } from 'react';
import type { Peak } from '../api/analysis';

type SortKey = 'wavenumber' | 'intensity' | 'prominence' | 'fwhm_cm1' | 'area';

const COLUMNS: Array<{ key: SortKey; label: string; unit?: string; title: string }> = [
  {
    key: 'wavenumber',
    label: 'Position',
    unit: 'cm⁻¹',
    title: 'Raman shift at the band apex',
  },
  { key: 'intensity', label: 'Intensity', title: 'Measured height at the apex' },
  {
    key: 'prominence',
    label: 'Prominence',
    title: 'How far the band rises above the surrounding baseline — the '
      + 'scale-independent measure of whether a peak is real',
  },
  {
    key: 'fwhm_cm1',
    label: 'FWHM',
    unit: 'cm⁻¹',
    title: 'Full width at half maximum — band width, which tracks crystallinity '
      + 'and disorder',
  },
  {
    key: 'area',
    label: 'Area',
    title: 'Gaussian-equivalent integrated intensity, from height and width',
  },
];

function formatCell(peak: Peak, key: SortKey): string {
  const value = peak[key];
  if (value === null || value === undefined) return '—';
  // Positions get one decimal (instrument resolution is ~1 cm-1, so more
  // would be false precision); everything else gets significant figures
  // appropriate to its magnitude.
  if (key === 'wavenumber' || key === 'fwhm_cm1') return value.toFixed(1);
  if (Math.abs(value) >= 1000) return value.toFixed(0);
  return value.toFixed(2);
}

export default function PeakTable({ peaks }: { peaks: Peak[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('wavenumber');
  const [descending, setDescending] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...peaks];
    copy.sort((a, b) => {
      // Nulls (an unmeasurable FWHM) always sort last, in both directions —
      // "no value" is never the most interesting row.
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null) return 1;
      if (bv === null) return -1;
      return descending ? bv - av : av - bv;
    });
    return copy;
  }, [peaks, sortKey, descending]);

  if (peaks.length === 0) {
    return (
      <p className="hint">
        No bands cleared the detection threshold. Lower the prominence or the noise
        rejection to look for weaker peaks.
      </p>
    );
  }

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setDescending((d) => !d);
    } else {
      setSortKey(key);
      // Position reads naturally low-to-high; every other column is a
      // "biggest first" question.
      setDescending(key !== 'wavenumber');
    }
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="sr-only">
          Detected Raman bands, sortable by position, intensity, prominence, width and area
        </caption>
        <thead>
          <tr>
            {COLUMNS.map((column) => (
              <th key={column.key} scope="col" title={column.title}>
                <button
                  type="button"
                  className="data-table__sort"
                  onClick={() => toggleSort(column.key)}
                  aria-sort={
                    sortKey === column.key
                      ? descending
                        ? 'descending'
                        : 'ascending'
                      : 'none'
                  }
                >
                  {column.label}
                  {column.unit && <span className="data-table__unit"> {column.unit}</span>}
                  <span aria-hidden="true" className="data-table__caret">
                    {sortKey === column.key ? (descending ? '▾' : '▴') : ''}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((peak) => (
            <tr key={peak.index}>
              {COLUMNS.map((column) => (
                <td key={column.key} className="data-table__num">
                  {formatCell(peak, column.key)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
