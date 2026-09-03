/**
 * A resolve hook that lets `node --test` load this package's sources directly.
 *
 * The workspace compiles with TypeScript's `moduleResolution: "bundler"`, so
 * relative imports are written without a file extension (`./numeric`). Node's
 * ESM loader requires one. Rather than push `allowImportingTsExtensions` into
 * every consumer's tsconfig — the web app typechecks package sources, so the
 * flag would have to spread — the mismatch is bridged here, where it belongs:
 * in the one place that runs these files under bare Node.
 */

import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const HAS_EXTENSION = /\.[cm]?[jt]sx?$|\.json$/;

export function resolve(specifier, context, nextResolve) {
  if (
    context.parentURL &&
    (specifier.startsWith("./") || specifier.startsWith("../")) &&
    !HAS_EXTENSION.test(specifier)
  ) {
    const candidate = new URL(`${specifier}.ts`, context.parentURL);
    if (existsSync(fileURLToPath(candidate))) {
      return nextResolve(candidate.href, context);
    }
  }
  return nextResolve(specifier, context);
}
