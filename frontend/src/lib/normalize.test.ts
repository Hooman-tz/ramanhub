import { describe, expect, it } from 'vitest';
import {
  applyDisplayNormalization,
  area,
  intensityAxisLabel,
  minmax,
  snv,
} from './normalize';

/** A Gaussian band pair — stands in for a real spectrum. */
function spectrum(scale = 1, offset = 0): { x: number[]; y: number[] } {
  const x: number[] = [];
  const y: number[] = [];
  for (let i = 0; i < 200; i += 1) {
    const wn = 400 + i * 7;
    const g = (c: number, a: number, w: number) =>
      a * Math.exp(-((wn - c) ** 2) / (2 * w * w));
    x.push(wn);
    y.push((50 + g(600, 100, 15) + g(1200, 60, 15)) * scale + offset);
  }
  return { x, y };
}

function mean(v: number[]) {
  return v.reduce((a, b) => a + b, 0) / v.length;
}

function std(v: number[]) {
  const mu = mean(v);
  return Math.sqrt(v.reduce((s, x) => s + (x - mu) ** 2, 0) / v.length);
}

describe('snv', () => {
  it('centres to zero mean and unit standard deviation', () => {
    const { y } = spectrum();
    const out = snv(y);
    expect(mean(out)).toBeCloseTo(0, 10);
    expect(std(out)).toBeCloseTo(1, 10);
  });

  it('is invariant to intensity scale — the whole reason it is the default', () => {
    // The same material measured at two laser powers. As stored these differ
    // by orders of magnitude and the larger flattens the smaller; after SNV
    // they must superimpose exactly.
    const bright = spectrum(1, 0);
    const dim = spectrum(0.001, 3);

    const a = snv(bright.y);
    const b = snv(dim.y);

    a.forEach((value, i) => expect(value).toBeCloseTo(b[i], 9));
  });

  it('returns finite values for a flat spectrum rather than dividing by zero', () => {
    const out = snv([5, 5, 5, 5]);
    expect(out.every(Number.isFinite)).toBe(true);
    expect(out).toEqual([0, 0, 0, 0]);
  });

  it('handles an empty array', () => {
    expect(snv([])).toEqual([]);
  });
});

describe('minmax', () => {
  it('scales into 0..1 inclusive', () => {
    const { y } = spectrum();
    const out = minmax(y);
    expect(Math.min(...out)).toBeCloseTo(0, 10);
    expect(Math.max(...out)).toBeCloseTo(1, 10);
  });

  it('collapses a flat spectrum to zeros instead of NaN', () => {
    expect(minmax([2, 2, 2])).toEqual([0, 0, 0]);
  });
});

describe('area', () => {
  it('normalizes to unit integrated area over the real axis', () => {
    const { x, y } = spectrum();
    const out = area(x, y);
    let total = 0;
    for (let i = 1; i < out.length; i += 1) {
      total += ((out[i] + out[i - 1]) / 2) * Math.abs(x[i] - x[i - 1]);
    }
    expect(total).toBeCloseTo(1, 8);
  });

  it('uses the wavenumber axis, not a bare sum — a non-uniform grid must still work', () => {
    // Two identical spectra, one on a grid twice as coarse. Unit area means
    // the coarse one is scaled differently; a naive sum would treat them the
    // same and get the density wrong.
    const fine = { x: [0, 1, 2, 3], y: [1, 1, 1, 1] };
    const coarse = { x: [0, 2, 4, 6], y: [1, 1, 1, 1] };
    expect(area(fine.x, fine.y)[0]).not.toBeCloseTo(area(coarse.x, coarse.y)[0], 6);
  });
});

describe('applyDisplayNormalization', () => {
  it('passes values through untouched for "none"', () => {
    const { x, y } = spectrum();
    expect(applyDisplayNormalization(x, y, 'none')).toEqual(y);
  });

  it('dispatches to each named transform', () => {
    const { x, y } = spectrum();
    expect(applyDisplayNormalization(x, y, 'snv')).toEqual(snv(y));
    expect(applyDisplayNormalization(x, y, 'minmax')).toEqual(minmax(y));
    expect(applyDisplayNormalization(x, y, 'area')).toEqual(area(x, y));
  });
});

describe('intensityAxisLabel', () => {
  it('states the transform so normalized values cannot be read as counts', () => {
    expect(intensityAxisLabel('snv')).toMatch(/SNV/);
    expect(intensityAxisLabel('minmax')).toMatch(/0–1/);
    expect(intensityAxisLabel('area')).toMatch(/area/);
    expect(intensityAxisLabel('none')).toBe('Intensity');
  });
});
