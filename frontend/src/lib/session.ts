/**
 * Local session storage for the opaque bearer token issued by the backend.
 *
 * The token is the only auth proof the browser keeps: profiles and other API
 * payloads are cached separately (see `offline/profile.ts`) and are never used
 * to authorize a request. There is no refresh flow — an expired or revoked
 * token means the user signs in again.
 */

/** Local storage key holding the opaque session token. */
export const TOKEN_STORAGE_KEY = "vidfetch.auth.token";

/** Window event emitted when the API rejects the stored token. */
export const UNAUTHORIZED_EVENT = "vidfetch:unauthorized";

/** Payload of `vidfetch:unauthorized`. */
export interface UnauthorizedDetail {
  /** Server message, when one was available. */
  message: string | null;
}

export type UnauthorizedListener = (message: string | null) => void;

const listeners = new Set<UnauthorizedListener>();

let memoryToken: string | null = null;
let memoryOnly = false;
let cachedStorage: Storage | null | undefined;

/** Resolve `localStorage` once; a blocked store degrades to memory only. */
function authStorage(): Storage | null {
  if (cachedStorage !== undefined) return cachedStorage;
  try {
    cachedStorage = window.localStorage;
  } catch {
    cachedStorage = null;
    memoryOnly = true;
  }
  return cachedStorage;
}

/** Current bearer token, or `null` when signed out. */
export function getToken(): string | null {
  if (memoryOnly) return memoryToken;
  const storage = authStorage();
  if (!storage) return memoryToken;
  try {
    return storage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    memoryOnly = true;
    return memoryToken;
  }
}

/** Persist a freshly issued token. */
export function setToken(token: string): void {
  memoryToken = token;
  const storage = authStorage();
  if (!storage) return;
  try {
    storage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Quota or privacy mode: keep the token in memory for this tab.
    memoryOnly = true;
  }
}

/** Forget the token (sign-out, or a rejected session). */
export function clearToken(): void {
  memoryToken = null;
  const storage = authStorage();
  if (!storage) return;
  try {
    storage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    memoryOnly = true;
  }
}

/**
 * Tell the app that the stored token was rejected.
 *
 * Both an in-app subscription and a window event are emitted so non-React code
 * (for example the offline replay) can react without importing the provider.
 */
export function notifyUnauthorized(message: string | null = null): void {
  listeners.forEach((listener) => {
    try {
      listener(message);
    } catch {
      // A failing listener must not block the others.
    }
  });
  window.dispatchEvent(
    new CustomEvent<UnauthorizedDetail>(UNAUTHORIZED_EVENT, {
      detail: { message },
    }),
  );
}

/** Subscribe to unauthorized notifications; returns the unsubscribe function. */
export function subscribeUnauthorized(listener: UnauthorizedListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
