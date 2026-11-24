import {
  getOfflineStatus,
  setPersistence,
  type PersistenceState,
} from "./status";

/**
 * Storage accounting and persistence helpers.
 *
 * Saved songs must survive eviction pressure, so the first successful media
 * copy asks the browser for persistent storage once. The result is kept in the
 * shared offline status store and shown read-only by the storage dialog.
 *
 * Everything here is best effort: a browser without the Storage API simply
 * reports `unsupported` and the media cache keeps working without a grant.
 */

/** Browser-reported origin usage, when the API is available. */
export interface StorageEstimate {
  /** Bytes already used by this origin (app shell, IndexedDB, media cache). */
  usage: number;
  /** Browser quota for this origin. */
  quota: number;
}

function storageManager(): StorageManager | null {
  if (typeof navigator === "undefined") return null;
  const storage = navigator.storage;
  return storage && typeof storage.persist === "function" ? storage : null;
}

/** True when this browser exposes the persistent-storage API. */
export function persistenceSupported(): boolean {
  return storageManager() !== null;
}

let persistenceRequest: Promise<PersistenceState> | null = null;

/**
 * Read the current persistent-storage grant without prompting.
 *
 * A successful `persisted()` answer is normalized to `granted`/`denied` and
 * written to the shared status store.
 */
export async function refreshPersistenceState(): Promise<PersistenceState> {
  const storage = storageManager();
  if (!storage) {
    setPersistence("unsupported");
    return "unsupported";
  }

  try {
    // A grant requested moments ago wins over a stale `persisted()` read.
    if (persistenceRequest) {
      const requested = await persistenceRequest;
      if (requested === "granted" || requested === "unsupported") {
        return requested;
      }
    }

    const granted =
      typeof storage.persisted === "function"
        ? await storage.persisted()
        : false;
    const next: PersistenceState = granted ? "granted" : "denied";
    setPersistence(next);
    return next;
  } catch {
    // Keep the previous answer; the dialog still renders a sane status.
    return getOfflineStatus().persistence;
  }
}

/**
 * Ask for persistent storage exactly once per session.
 *
 * Called after the first successful offline save. A prior grant, a refusal and
 * an unsupported browser are all remembered so `persist()` is never spammed.
 */
export function requestPersistentStorageOnce(): Promise<PersistenceState> {
  if (persistenceRequest) return persistenceRequest;

  const storage = storageManager();
  if (!storage) {
    setPersistence("unsupported");
    persistenceRequest = Promise.resolve("unsupported");
    return persistenceRequest;
  }

  persistenceRequest = (async (): Promise<PersistenceState> => {
    try {
      if (
        typeof storage.persisted === "function" &&
        (await storage.persisted())
      ) {
        setPersistence("granted");
        return "granted";
      }

      const granted = await storage.persist();
      const next: PersistenceState = granted ? "granted" : "denied";
      setPersistence(next);
      return next;
    } catch {
      setPersistence("denied");
      return "denied";
    }
  })();

  return persistenceRequest;
}

/**
 * Read `navigator.storage.estimate()`, or `null` when it is unavailable.
 *
 * A zero quota is treated as unavailable: browsers that report no quota give
 * the UI nothing meaningful to show.
 */
export async function readStorageEstimate(): Promise<StorageEstimate | null> {
  if (typeof navigator === "undefined") return null;
  const storage = navigator.storage;
  if (!storage || typeof storage.estimate !== "function") return null;

  try {
    const estimate = await storage.estimate();
    const usage = Math.max(0, estimate.usage ?? 0);
    const quota = Math.max(0, estimate.quota ?? 0);
    return quota > 0 ? { usage, quota } : null;
  } catch {
    return null;
  }
}
