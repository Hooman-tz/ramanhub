import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import SpectrumTable from './SpectrumTable';
import type { SpectrumSearchResult } from '../api/search';

const ROWS: SpectrumSearchResult[] = [
  {
    id: 'a', accession: 'RH-S-000001', title: 'Polystyrene', material_type: 'polystyrene',
    excitation_wavelength_nm: 532, snr: 42.5, modality: 'raman', doi: '10.1/x',
    owner_id: 'u1', published_at: '2026-01-02T00:00:00Z', state: 'published',
  },
  {
    id: 'b', accession: 'RH-S-000002', title: 'Calcite', material_type: 'calcite',
    excitation_wavelength_nm: 785, snr: 12.0, modality: 'raman', doi: null,
    owner_id: 'u1', published_at: '2026-03-04T00:00:00Z', state: 'draft',
  },
] as SpectrumSearchResult[];

function renderTable(selected = new Set<string>(), onChange = vi.fn()) {
  render(
    <MemoryRouter>
      <SpectrumTable rows={ROWS} selected={selected} onSelectedChange={onChange} />
    </MemoryRouter>,
  );
  return onChange;
}

describe('SpectrumTable', () => {
  it('links each spectrum by its own id', () => {
    renderTable();
    expect(screen.getByRole('link', { name: /Polystyrene/ })).toHaveAttribute(
      'href',
      '/spectra/a',
    );
  });

  it('shows the citable accession alongside the title', () => {
    renderTable();
    expect(screen.getByText('RH-S-000001')).toBeInTheDocument();
  });

  it('marks DOI-verified rows', () => {
    renderTable();
    // Only the first row has a DOI.
    expect(screen.getAllByText('DOI')).toHaveLength(1);
  });

  it('adds a row to the selection when its checkbox is ticked', async () => {
    const user = userEvent.setup();
    const onChange = renderTable();

    await user.click(screen.getByRole('checkbox', { name: /Select Polystyrene/ }));

    expect(onChange).toHaveBeenCalledWith(new Set(['a']));
  });

  it('removes an already-selected row when ticked again', async () => {
    const user = userEvent.setup();
    const onChange = renderTable(new Set(['a']));

    await user.click(screen.getByRole('checkbox', { name: /Select Polystyrene/ }));

    expect(onChange).toHaveBeenCalledWith(new Set());
  });

  it('select-all adds every row on the page', async () => {
    const user = userEvent.setup();
    const onChange = renderTable();

    await user.click(screen.getByRole('checkbox', { name: /Select all/ }));

    expect(onChange).toHaveBeenCalledWith(new Set(['a', 'b']));
  });

  it('shows an indeterminate header checkbox for a partial selection', () => {
    renderTable(new Set(['a']));
    const header = screen.getByRole('checkbox', { name: /Select all/ }) as HTMLInputElement;
    expect(header.indeterminate).toBe(true);
    expect(header.checked).toBe(false);
  });

  it('renders a dash for missing measurements rather than blank cells', () => {
    render(
      <MemoryRouter>
        <SpectrumTable
          rows={[{ ...ROWS[0], snr: null, material_type: null } as SpectrumSearchResult]}
          selected={new Set()}
          onSelectedChange={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });

  it('can hide the state column on surfaces where everything is published', () => {
    render(
      <MemoryRouter>
        <SpectrumTable
          rows={ROWS}
          selected={new Set()}
          onSelectedChange={vi.fn()}
          showState={false}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText('draft')).not.toBeInTheDocument();
  });
});
