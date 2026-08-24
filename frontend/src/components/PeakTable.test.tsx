import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PeakTable from './PeakTable';
import type { Peak } from '../api/analysis';

const PEAKS: Peak[] = [
  { index: 10, wavenumber: 1002.4, intensity: 139.1, prominence: 105.8, fwhm_cm1: 11.2, area: 1260 },
  { index: 4, wavenumber: 622.0, intensity: 69.9, prominence: 40.2, fwhm_cm1: 16.1, area: 690 },
  { index: 30, wavenumber: 1602.0, intensity: 96.3, prominence: 88.4, fwhm_cm1: null, area: 0 },
];

function positions() {
  const rows = screen.getAllByRole('row').slice(1); // drop the header
  return rows.map((row) => within(row).getAllByRole('cell')[0].textContent);
}

describe('PeakTable', () => {
  it('renders one row per detected band', () => {
    render(<PeakTable peaks={PEAKS} />);
    expect(screen.getAllByRole('row')).toHaveLength(PEAKS.length + 1);
  });

  it('sorts by wavenumber ascending by default — reading order for a spectroscopist', () => {
    render(<PeakTable peaks={PEAKS} />);
    expect(positions()).toEqual(['622.0', '1002.4', '1602.0']);
  });

  it('reverses the sort when the active column header is clicked again', async () => {
    const user = userEvent.setup();
    render(<PeakTable peaks={PEAKS} />);

    await user.click(screen.getByRole('button', { name: /Position/ }));

    expect(positions()).toEqual(['1602.0', '1002.4', '622.0']);
  });

  it('sorts a different column biggest-first, since that is the question being asked', async () => {
    const user = userEvent.setup();
    render(<PeakTable peaks={PEAKS} />);

    await user.click(screen.getByRole('button', { name: /Prominence/ }));

    expect(positions()).toEqual(['1002.4', '1602.0', '622.0']);
  });

  it('keeps unmeasurable values last in both directions', async () => {
    const user = userEvent.setup();
    render(<PeakTable peaks={PEAKS} />);

    // 1602 has a null FWHM; it must not lead either ordering.
    await user.click(screen.getByRole('button', { name: /FWHM/ }));
    expect(positions()[2]).toBe('1602.0');

    await user.click(screen.getByRole('button', { name: /FWHM/ }));
    expect(positions()[2]).toBe('1602.0');
  });

  it('renders a dash rather than "null" for a missing width', () => {
    render(<PeakTable peaks={PEAKS} />);
    const row = screen.getAllByRole('row').find((r) => r.textContent?.includes('1602.0'))!;
    expect(within(row).getAllByRole('cell')[3]).toHaveTextContent('—');
  });

  it('explains what to do when nothing cleared the threshold', () => {
    render(<PeakTable peaks={[]} />);
    expect(screen.getByText(/No bands cleared/i)).toBeInTheDocument();
    expect(screen.getByText(/Lower the prominence/i)).toBeInTheDocument();
  });

  it('exposes sort state to assistive technology', async () => {
    const user = userEvent.setup();
    render(<PeakTable peaks={PEAKS} />);

    const position = screen.getByRole('button', { name: /Position/ });
    expect(position).toHaveAttribute('aria-sort', 'ascending');

    await user.click(position);
    expect(position).toHaveAttribute('aria-sort', 'descending');
  });
});
