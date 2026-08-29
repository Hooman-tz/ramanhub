import { defineConfig } from "eslint/config";

import { baseConfig, restrictEnvAccess } from "@ramanhub/eslint-config/base";
import { nextjsConfig } from "@ramanhub/eslint-config/nextjs";
import { reactConfig } from "@ramanhub/eslint-config/react";

export default defineConfig(
  {
    ignores: [".next/**"],
  },
  baseConfig,
  reactConfig,
  nextjsConfig,
  restrictEnvAccess,
);
