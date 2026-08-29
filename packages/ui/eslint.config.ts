import { defineConfig } from "eslint/config";

import { baseConfig } from "@ramanhub/eslint-config/base";
import { reactConfig } from "@ramanhub/eslint-config/react";

export default defineConfig(
  {
    ignores: ["dist/**"],
  },
  baseConfig,
  reactConfig,
);
