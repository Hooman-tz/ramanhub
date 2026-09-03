import { defineConfig } from "eslint/config";

import { baseConfig } from "@ramanhub/eslint-config/base";

export default defineConfig(
  {
    ignores: ["dist/**"],
  },
  baseConfig,
  {
    // This package is numeric kernels: indexed reads inside counted loops,
    // thousands of them. `noUncheckedIndexedAccess` types every one of those
    // as `number | undefined`, so the workspace-wide ban on `!` would force a
    // `?? 0` onto each — which is strictly worse than the assertion. It buries
    // the arithmetic in noise, and it turns a genuine out-of-bounds bug into a
    // silent zero that quietly corrupts a spectrum instead of throwing.
    //
    // Every index here is bounded by the array's own `.length`, and the ports
    // are checked against the Python registry's actual output by
    // `test/parity.test.ts`. That fixture is the real guarantee; the lint rule
    // was never going to be.
    //
    // `prefer-for-of` is off for a narrower reason: most of these functions
    // take `ArrayLike<number>` so they accept both plain arrays and typed
    // arrays, and `ArrayLike` is not iterable — `for..of` does not typecheck
    // on it. Converting only the loops where it happens to compile would
    // leave the kernels inconsistent for no benefit.
    files: ["src/**/*.ts", "test/**/*.ts"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/prefer-for-of": "off",
    },
  },
);
