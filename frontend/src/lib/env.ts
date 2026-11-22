/**
 * Feature flags read from Vite environment variables.
 *
 * Vite statically replaces `import.meta.env.*` at build time, so disabled
 * branches (for example the local email/password form) never become
 * reachable in a production bundle built without the flag.
 */

/**
 * Development-only email/password sign-in.
 *
 * This is intentionally opt-in: production builds (Vercel) must not set
 * `VITE_ENABLE_LOCAL_AUTH`, which keeps the only production sign-in path as
 * Google OAuth against the hosted Supabase project.
 */
export const isLocalAuthEnabled =
  import.meta.env.VITE_ENABLE_LOCAL_AUTH === "true";
