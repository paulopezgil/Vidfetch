import { useSyncExternalStore } from "react";
import { countQueue } from "./db";

/** Copy shown after a mutation is stored for later replay. */
export const QUEUED_MUTATION_MESSAGE =
  "Desat al dispositiu; es sincronitzarà quan torni la connexió.";

/** How the browser answers the persistent-storage request. */
export type PersistenceState =
  | "unknown"
  | "granted"
  | "denied"
  | "unsupported";

const persistentStorageSupported =
  typeof navigator !== "undefined" &&
  typeof navigator.storage?.persist === "function";

/** Snapshot consumed by the offline banner and other UI. */
export interface OfflineStatus {
  /** Network reachable according to `navigator.onLine` and recent requests. */
  online: boolean;
  /** Mutations stored locally and waiting for a replay. */
  pending: number;
  /** True while a flush is running. */
  syncing: boolean;
  /** True when the last data shown came from the local read cache. */
  usingCache: boolean;
  /** Last network/sync problem, if any. */
  lastError: string | null;
  /** When the currently displayed cached data was stored. */
  cachedAt: number | null;
  /** Persistent-storage grant, remembered for the storage dialog. */
  persistence: PersistenceState;
}

const browserOnline =
  typeof navigator === "undefined" || navigator.onLine !== false;

let state: OfflineStatus = {
  online: browserOnline,
  pending: 0,
  syncing: false,
  usingCache: false,
  lastError: null,
  cachedAt: null,
  persistence: persistentStorageSupported ? "unknown" : "unsupported",
};

const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

function update(patch: Partial<OfflineStatus>): void {
  const next = { ...state, ...patch };
  const unchanged = (
    Object.keys(next) as (keyof OfflineStatus)[]
  ).every((key) => next[key] === state[key]);
  if (unchanged) return;
  state = next;
  emit();
}

/** Current snapshot, stable between updates. */
export function getOfflineStatus(): OfflineStatus {
  return state;
}

/** Subscribe to status changes (`useSyncExternalStore` compatible). */
export function subscribeOfflineStatus(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React binding for the status store. */
export function useOfflineStatus(): OfflineStatus {
  return useSyncExternalStore(
    subscribeOfflineStatus,
    getOfflineStatus,
    getOfflineStatus,
  );
}

/** A request reached the server: the connection is usable again. */
export function reportNetworkSuccess(): void {
  update({ online: true, usingCache: false, lastError: null });
}

/** A request failed before any HTTP response arrived. */
export function reportNetworkFailure(message: string): void {
  update({ online: false, lastError: message });
}

/** The API was unreachable, so cached data is on screen. */
export function markCacheServed(savedAt: number): void {
  update({ usingCache: true, cachedAt: savedAt, online: false });
}

/**
 * Forget the queue/cache flags after a sign-out.
 *
 * The next account on this browser must not inherit the previous user's
 * pending count, sync spinner, "served from cache" marker or last error. The
 * connection state stays: it describes the browser, not the account.
 */
export function resetOfflineStatus(): void {
  update({
    pending: 0,
    syncing: false,
    usingCache: false,
    cachedAt: null,
    lastError: null,
  });
}

/** Publish a freshly counted queue length. */
export function setPending(pending: number): void {
  update({ pending: Math.max(0, pending) });
}

/** Re-read the queue length from IndexedDB. */
export async function refreshPendingCount(): Promise<void> {
  setPending(await countQueue());
}

/** Flag the flush lifecycle for the banner. */
export function setSyncing(syncing: boolean): void {
  update({ syncing });
}

/** Record why the last replay stopped or skipped an entry. */
export function setLastError(lastError: string | null): void {
  update({ lastError });
}

/** Remember the result of the persistent-storage request. */
export function setPersistence(persistence: PersistenceState): void {
  update({ persistence });
}

/** True when the app should assume there is no usable connection. */
export function isOffline(): boolean {
  if (!state.online) return true;
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

if (typeof window !== "undefined") {
  window.addEventListener("online", () => {
    update({ online: true, lastError: null });
  });
  window.addEventListener("offline", () => {
    update({ online: false });
  });
}
