/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Base path for API calls. Defaults to "/api" (proxied to the API in dev and prod). Override at
  // build time with VITE_API_BASE for an atypical deployment.
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
