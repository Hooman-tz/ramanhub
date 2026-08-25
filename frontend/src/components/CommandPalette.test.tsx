import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { useState } from 'react';
import CommandPalette from './CommandPalette';
import type { SpectrumSearchResult } from '../api/search';

const searchSpectra = vi.hoisted(() => vi.fn());
vi.mock('../api/search', () => ({ searchSpectra }));

const HIT = {
  id: 'abc', accession: 'RH-S-000042', title: 'Rhodamine 6G', material_type: 'rhodamine',
  excitation_wavelength_nm: 532, snr: 30, modality: 'raman', doi: null,
  owner_id: 'u1', published_at: '2026-01-01T00:00:00Z', state: 'published',
} as SpectrumSearchResult;

/** Shows where the router ended up, so navigation assertions test the actual
 * outcome rather than that a handler was called. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}</div>;
}

/** Mirrors how AppShell owns the open state — the palette is controlled. */
function Harness({ initialOpen = true }: { initialOpen?: boolean }) {
  const [open, setOpen] = useState(initialOpen);
  return (
    <MemoryRouter initialEntries={['/upload']}>
      <CommandPalette open={open} onOpenChange={setOpen} />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('CommandPalette', () => {
  beforeEach(() => {
    searchSpectra.mockReset();
    searchSpectra.mockResolvedValue([]);
  });

  it('renders nothing while closed', () => {
    render(<Harness initialOpen={false} />);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens on the platform shortcut', async () => {
    const user = userEvent.setup();
    render(<Harness initialOpen={false} />);
    await user.keyboard('{Meta>}k{/Meta}');
    expect(await screen.findByRole('dialog', { name: /command palette/i })).toBeInTheDocument();
  });

  it('filters the navigation commands as you type', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('textbox'), 'routi');

    expect(screen.getByRole('option', { name: /Routines/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Trending/ })).toBeNull();
  });

  it('navigates on Enter', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('textbox'), 'compare{Enter}');

    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/compare'));
  });

  it('moves the selection with the arrow keys', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByRole('textbox');

    const first = screen.getAllByRole('option')[0];
    expect(first).toHaveAttribute('aria-selected', 'true');

    await user.type(input, '{ArrowDown}');
    expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'false');
  });

  it('does not query the corpus for a one-character term', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('textbox'), 'r');

    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(searchSpectra).not.toHaveBeenCalled();
  });

  it('offers corpus hits by accession permalink, not raw id', async () => {
    searchSpectra.mockResolvedValue([HIT]);
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('textbox'), 'rhodamine');

    const hit = await screen.findByRole('option', { name: /Rhodamine 6G/ });
    await user.click(hit);

    // The accession is the form that survives in a printed citation, so it is
    // the one the palette should route to when the spectrum has one.
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/s/RH-S-000042'));
  });

  it('closes on Escape without navigating', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByRole('textbox'), '{Escape}');

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.getByTestId('where')).toHaveTextContent('/upload');
  });
});
