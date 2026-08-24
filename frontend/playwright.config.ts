import { defineConfig, devices } from '@playwright/test';

/** E2E config.
 *
 * Assumes the API is already running at API_BASE_URL with a seeded database
 * (`make migrate && make seed && make seed-demo`) — Playwright starts the
 * frontend but deliberately not the backend, because a browser test that
 * silently spins up its own API is a test that can pass against the wrong
 * database. CI wires both explicitly.
 */
const PORT = 4173;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    // Traces only for a failure that survived a retry — full traces on every
    // run are large and nobody reads them.
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // A phone viewport, because the responsive layout is a real requirement
    // and desktop-only E2E is how mobile regressions ship.
    { name: 'mobile', use: { ...devices['Pixel 5'] } },
  ],
  webServer: {
    command: `npm run build && npx vite preview --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
