/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_API_BASE?: string;
  /**
   * Development-only flag: `"true"` enables email/password sign-in against
   * Supabase Auth. Never set this in a production (Vercel) build.
   */
  readonly VITE_ENABLE_LOCAL_AUTH?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
