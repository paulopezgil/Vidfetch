/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute API origin when the frontend is hosted apart from the backend. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
