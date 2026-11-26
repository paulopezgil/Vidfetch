import { useSyncExternalStore } from "react";
import { getMediaToken } from "../lib/api";
import {
  listMediaEntries,
  putMediaEntry,
  readMediaEntry,
  type OfflineMediaEntry,
} from "./db";
import { requestPersistentStorageOnce } from "./storage";

/**
 * Local media cache.
 *
 * Completed audio transfers are copied into Cache Storage under a synthetic,
 * same-origin path so they never collide with real API routes. A matching
 * IndexedDB row keeps the size and MIME type for fast state checks and storage
 * usage accounting.
 *
 * Every helper fails closed: without Cache Storage or IndexedDB the app keeps
 * working online and playback simply falls back to the signed URL.
 */
export const MEDIA_CACHE_NAME = "vidfetch-media-v1";

/** Synthetic Cache Storage path, one entry per asset. */
export const MEDIA_KEY_PREFIX = "/__vidfetch_offline__/media/";

/** At most two transfers run at once, so parallel jobs stay polite. */
const MAX_CONCURRENT_SAVES = 2;

const STORAGE_UNAVAILABLE =
  "Aquest navegador no permet desar mitjans per a escoltar sense connexió.";

const SAVE_FAILED = "No s’ha pogut desar el fitxer per a escoltar sense connexió.";

/**
 * Shown when the browser refuses a media copy for lack of space.
 *
 * The cloud copy stays untouched: only the local transfer is abandoned.
 */
export const QUOTA_EXCEEDED_MESSAGE =
  "No hi ha prou espai al dispositiu per desar aquesta cançó sense connexió.";

/** Normalize the different quota error shapes across browsers. */
function isQuotaError(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const name = "name" in error ? String(error.name) : "";
  const message = "message" in error ? String(error.message) : "";
  return (
    name === "QuotaExceededError" ||
    name === "NS_ERROR_DOM_QUOTA_REACHED" ||
    /quota/i.test(message)
  );
}

const AUDIO_EXTENSIONS = new Set([
  "mp3",
  "m4a",
  "aac",
  "wav",
  "flac",
  "ogg",
  "opus",
]);

/** True when a yt-dlp selector asks for a plain audio download. */
export function isAudioSelector(selector: string | null | undefined): boolean {
  const value = (selector ?? "").toLowerCase();
  return value.includes("mp3") || value.includes("bestaudio");
}

/** True when a track/asset is an audio song. */
export function isAudioAsset(input: {
  output_ext?: string | null;
  format_selector?: string | null;
}): boolean {
  const ext = (input.output_ext ?? "").replace(/^\./, "").toLowerCase();
  if (AUDIO_EXTENSIONS.has(ext)) return true;
  return isAudioSelector(input.format_selector);
}

export interface OfflineMediaStatus {
  /** True once the IndexedDB index has been read at least once. */
  loaded: boolean;
  /** Asset ids with a local copy. */
  saved: ReadonlySet<string>;
  /** Asset ids with a transfer queued or running. */
  saving: ReadonlySet<string>;
  /** Last failure per asset id, cleared on the next successful save. */
  errors: Readonly<Record<string, string>>;
  /** Number of saved media copies. */
  count: number;
  /** Total bytes held by the local media cache. */
  bytes: number;
}

const initialStatus: OfflineMediaStatus = {
  loaded: false,
  saved: new Set(),
  saving: new Set(),
  errors: {},
  count: 0,
  bytes: 0,
};

let status: OfflineMediaStatus = initialStatus;
const listeners = new Set<() => void>();

function emit(): void {
  listeners.forEach((listener) => listener());
}

function update(patch: Partial<OfflineMediaStatus>): void {
  status = { ...status, ...patch };
  emit();
}

function setSaving(assetId: string, saving: boolean): void {
  const next = new Set(status.saving);
  if (saving) next.add(assetId);
  else next.delete(assetId);
  if (next.size === status.saving.size) return;
  update({ saving: next });
}

function recordError(assetId: string, message: string): void {
  update({ errors: { ...status.errors, [assetId]: message } });
}

function clearError(assetId: string): void {
  if (!(assetId in status.errors)) return;
  const next = { ...status.errors };
  delete next[assetId];
  update({ errors: next });
}

function adoptEntry(entry: OfflineMediaEntry): void {
  if (status.saved.has(entry.assetId)) return;
  const saved = new Set(status.saved);
  saved.add(entry.assetId);
  update({
    saved,
    count: saved.size,
    bytes: status.bytes + Math.max(0, entry.size || 0),
  });
}

/** Current snapshot, stable between updates. */
export function getOfflineMediaStatus(): OfflineMediaStatus {
  return status;
}

/** Subscribe to media-cache changes (`useSyncExternalStore` compatible). */
export function subscribeOfflineMedia(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** React binding for the media-cache status. */
export function useOfflineMedia(): OfflineMediaStatus {
  return useSyncExternalStore(
    subscribeOfflineMedia,
    getOfflineMediaStatus,
    getOfflineMediaStatus,
  );
}

/** True when the browser exposes both stores the cache depends on. */
function storageAvailable(): boolean {
  return (
    typeof caches !== "undefined" &&
    typeof indexedDB !== "undefined" &&
    typeof Response !== "undefined"
  );
}

/** Stable Cache Storage key for one asset. */
export function offlineMediaKey(assetId: string): string {
  return `${MEDIA_KEY_PREFIX}${encodeURIComponent(assetId)}`;
}

let loadPromise: Promise<OfflineMediaStatus> | null = null;

/**
 * Read the IndexedDB media index into the status store.
 *
 * Called once when the app shell mounts; a second call reuses the in-flight or
 * settled promise unless `force` is set.
 */
export function loadOfflineIndex(force = false): Promise<OfflineMediaStatus> {
  if (loadPromise && !force) return loadPromise;

  loadPromise = listMediaEntries().then((entries) => {
    const saved = new Set(entries.map((entry) => entry.assetId));
    const bytes = entries.reduce(
      (total, entry) => total + Math.max(0, entry.size || 0),
      0,
    );
    update({
      loaded: true,
      saved,
      count: saved.size,
      bytes,
    });
    return status;
  });

  return loadPromise;
}

/**
 * Recompute saved media from IndexedDB.
 *
 * Returns the number of copies and their total size; the status store is
 * refreshed as a side effect.
 */
export async function estimateOfflineUsage(): Promise<{
  count: number;
  bytes: number;
}> {
  const entries = await listMediaEntries();
  const saved = new Set(entries.map((entry) => entry.assetId));
  const bytes = entries.reduce(
    (total, entry) => total + Math.max(0, entry.size || 0),
    0,
  );
  update({ loaded: true, saved, count: saved.size, bytes });
  return { count: saved.size, bytes };
}

/** Whether an asset already has a local copy (fast, from the status store). */
export function hasOfflineMedia(assetId: string): boolean {
  return status.saved.has(assetId);
}

/** Last error recorded for an asset, if any. */
export function offlineMediaError(assetId: string): string | null {
  return status.errors[assetId] ?? null;
}

/** Read the locally cached blob for an asset, or `null` when missing. */
export async function getOfflineMediaBlob(
  assetId: string,
): Promise<Blob | null> {
  if (!assetId || typeof caches === "undefined") return null;
  try {
    const cache = await caches.open(MEDIA_CACHE_NAME);
    const response = await cache.match(offlineMediaKey(assetId));
    if (!response) return null;
    return await response.blob();
  } catch {
    return null;
  }
}

interface SaveTask {
  assetId: string;
  resolve: (ok: boolean) => void;
}

const queue: SaveTask[] = [];
const inFlight = new Map<string, Promise<boolean>>();
let activeSaves = 0;

function pump(): void {
  while (activeSaves < MAX_CONCURRENT_SAVES && queue.length > 0) {
    const task = queue.shift();
    if (!task) return;
    activeSaves += 1;
    void transfer(task)
      .catch(() => false)
      .then((ok) => {
        task.resolve(ok);
      })
      .finally(() => {
        activeSaves -= 1;
        pump();
      });
  }
}

/**
 * Delete a Cache Storage entry that was written only partially.
 *
 * Internal rollback only: there is no user-facing path that removes a saved
 * song. The IndexedDB metadata row is written only after a complete cache
 * write, so it is left untouched; this keeps a copy saved by another tab safe.
 */
async function rollbackMediaCopy(assetId: string): Promise<void> {
  // A complete copy may have been indexed by another tab in the meantime;
  // never discard a saved song just because this transfer failed.
  const saved = await readMediaEntry(assetId);
  if (saved) {
    adoptEntry(saved);
    return;
  }

  try {
    if (typeof caches !== "undefined") {
      const cache = await caches.open(MEDIA_CACHE_NAME);
      await cache.delete(offlineMediaKey(assetId));
    }
  } catch {
    // The entry may never have been written; nothing else to clean up.
  }
}

async function transfer(task: SaveTask): Promise<boolean> {
  const { assetId } = task;
  let cacheAttempted = false;

  try {
    const token = await getMediaToken(assetId);
    if (!token?.url) throw new Error(SAVE_FAILED);

    const response = await fetch(token.url, {
      credentials: "omit",
      cache: "no-store",
    });
    if (!response.ok) throw new Error(SAVE_FAILED);

    const blob = await response.blob();
    if (blob.size <= 0) throw new Error(SAVE_FAILED);

    const mime = blob.type || "audio/mpeg";
    const cache = await caches.open(MEDIA_CACHE_NAME);
    cacheAttempted = true;
    await cache.put(
      offlineMediaKey(assetId),
      new Response(blob, {
        headers: {
          "Content-Type": mime,
          "Content-Length": String(blob.size),
        },
      }),
    );

    const entry: OfflineMediaEntry = {
      assetId,
      size: blob.size,
      savedAt: Date.now(),
      mime,
    };
    const stored = await putMediaEntry(entry);
    if (!stored) {
      // Keep the two stores consistent: no metadata means no copy.
      throw new Error(STORAGE_UNAVAILABLE);
    }

    adoptEntry(entry);
    clearError(assetId);
    // First successful copy: ask the browser to keep it across eviction.
    void requestPersistentStorageOnce();
    return true;
  } catch (error) {
    const quota = isQuotaError(error);
    if (cacheAttempted || quota) {
      // A quota failure can leave a partial Cache Storage entry behind.
      await rollbackMediaCopy(assetId);
    }
    const message =
      quota
        ? QUOTA_EXCEEDED_MESSAGE
        : error instanceof Error && error.message
          ? error.message
          : SAVE_FAILED;
    recordError(assetId, message);
    return false;
  } finally {
    setSaving(assetId, false);
  }
}

/**
 * Copy an asset into the local media cache.
 *
 * Resolves `true` when a copy exists at the end (including one that was
 * already saved), `false` when the transfer failed. At most two transfers run
 * at once; repeated calls for the same asset share one transfer.
 */
export function saveOfflineMedia(assetId: string): Promise<boolean> {
  if (!assetId) return Promise.resolve(false);

  const running = inFlight.get(assetId);
  if (running) return running;
  if (status.saved.has(assetId)) return Promise.resolve(true);

  const promise = (async (): Promise<boolean> => {
    if (!storageAvailable()) {
      recordError(assetId, STORAGE_UNAVAILABLE);
      return false;
    }
    // index may still be loading; never download a copy we already hold.
    const existing = await readMediaEntry(assetId);
    if (existing) {
      adoptEntry(existing);
      return true;
    }

    setSaving(assetId, true);
    return new Promise<boolean>((resolve) => {
      queue.push({ assetId, resolve });
      pump();
    });
  })();

  inFlight.set(assetId, promise);
  void promise.then(
    () => inFlight.delete(assetId),
    () => inFlight.delete(assetId),
  );
  return promise;
}
