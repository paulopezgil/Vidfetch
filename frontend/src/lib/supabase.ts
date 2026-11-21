import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL?.trim();
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim();

/**
 * Human-readable configuration error. It is `null` when both environment
 * variables are present.
 *
 * This deliberately never reads (or expects) a service-role key: the browser
 * may only ever hold the public anon key.
 */
export const supabaseConfigError: string | null =
  !url && !anonKey
    ? "Falta la configuració de Supabase: defineix VITE_SUPABASE_URL i VITE_SUPABASE_ANON_KEY."
    : !url
      ? "Falta VITE_SUPABASE_URL a la configuració de l'aplicació."
      : !anonKey
        ? "Falta VITE_SUPABASE_ANON_KEY a la configuració de l'aplicació."
        : null;

/**
 * Supabase client for Auth only. `null` means the app was built without the
 * required environment variables; callers surface `supabaseConfigError`
 * instead of crashing at import time.
 */
export const supabase: SupabaseClient | null =
  url && anonKey
    ? createClient(url, anonKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
          flowType: "pkce",
        },
      })
    : null;

/** True when the public Supabase configuration is complete. */
export const isSupabaseConfigured = supabase !== null;
