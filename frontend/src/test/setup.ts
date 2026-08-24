import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(cleanup);

// jsdom implements neither of these, and both are used by code under test:
// ECharts measures its container on init, and ThemeToggle asks the OS for a
// colour-scheme preference. Stubbing them here keeps every component test
// from having to repeat the same boilerplate.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
});

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// @ts-expect-error - assigning a stub onto the jsdom global
globalThis.ResizeObserver = globalThis.ResizeObserver ?? ResizeObserverStub;
