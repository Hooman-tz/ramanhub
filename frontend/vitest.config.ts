import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Playwright specs live in e2e/ and are driven by `npm run test:e2e`;
    // without this exclusion Vitest would try to collect them and fail on
    // the @playwright/test imports.
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
  },
});
