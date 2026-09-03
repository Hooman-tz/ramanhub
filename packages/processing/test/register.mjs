/** Installs `bundler-resolve.mjs` for the test run. See that file for why. */
import { register } from "node:module";

register("./bundler-resolve.mjs", import.meta.url);
