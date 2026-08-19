/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  // Optional. "owner/repo" on GitHub, used by ReportBugButton to deep-link
  // into a pre-filled "New Issue" form. If unset, the button hides itself.
  readonly VITE_GITHUB_REPO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
