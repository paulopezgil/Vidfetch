import type { Profile } from "../types/auth";

/**
 * Per-user offline copy of the caller profile.
 *
 * Only the profile returned by `GET /api/me` is stored, never a token: the
 * Supabase session stays the auth source of truth. The key includes the user
 * id so switching accounts on the same browser cannot leak another profile.
 */
const PROFILE_KEY_PREFIX = "vidfetch.profile.";

function profileKey(userId: string): string {
  return `${PROFILE_KEY_PREFIX}${userId}`;
}

function isProfile(value: unknown, userId: string): value is Profile {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<Profile>;
  return (
    candidate.id === userId &&
    typeof candidate.email === "string" &&
    typeof candidate.is_approved === "boolean" &&
    (candidate.app_role === "admin" || candidate.app_role === "user")
  );
}

/** Remember the latest profile so the shell can boot offline. */
export function cacheProfile(profile: Profile): void {
  try {
    window.localStorage.setItem(profileKey(profile.id), JSON.stringify(profile));
  } catch {
    // Storage full or blocked: the online flow keeps working.
  }
}

/** Read the cached profile for one user, validating its shape. */
export function readCachedProfile(userId: string): Profile | null {
  try {
    const raw = window.localStorage.getItem(profileKey(userId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isProfile(parsed, userId) ? parsed : null;
  } catch {
    return null;
  }
}

/** Remove the cached profile on sign-out. */
export function clearCachedProfile(userId: string): void {
  try {
    window.localStorage.removeItem(profileKey(userId));
  } catch {
    // Nothing to do: the cache simply becomes unusable.
  }
}
