import type { Profile } from "../types/auth";

/**
 * Offline copy of the caller profile, used only to boot the shell when the
 * network is down.
 *
 * Only the profile returned by `GET /api/me` (or by a successful sign-in) is
 * stored — never a token or password. The bearer token stays the auth source of
 * truth, and this cache is only read while a token is present.
 */
const PROFILE_KEY = "vidfetch.profile.active";

function isProfile(value: unknown): value is Profile {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<Profile>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.email === "string" &&
    typeof candidate.is_approved === "boolean" &&
    (candidate.app_role === "admin" || candidate.app_role === "user")
  );
}

/** Remember the latest profile so the shell can boot offline. */
export function cacheProfile(profile: Profile): void {
  try {
    window.localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
  } catch {
    // Storage full or blocked: the online flow keeps working.
  }
}

/** Read the cached profile, validating its shape. */
export function readCachedProfile(): Profile | null {
  try {
    const raw = window.localStorage.getItem(PROFILE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isProfile(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Remove the cached profile on sign-out. */
export function clearCachedProfile(): void {
  try {
    window.localStorage.removeItem(PROFILE_KEY);
  } catch {
    // Nothing to do: the cache simply becomes unusable.
  }
}
