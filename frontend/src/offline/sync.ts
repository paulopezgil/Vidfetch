import { authorizedFetch, isNetworkError, parseError } from "../lib/api";
import {
  clearCachedResponses,
  countQueue,
  listQueue,
  removeQueue,
  updateQueue,
} from "./db";
import { setLastError, setPending, setSyncing } from "./status";

/**
 * Cached GETs that can go stale after a replay. Tracks and curated playlists
 * are the only resources the queued mutations touch, so only those entries are
 * dropped; the next online fetch repopulates them.
 */
const LIBRARY_CACHE_PREFIXES = ["/tracks", "/playlists", "/user-playlists"];

let flushing: Promise<void> | null = null;

function messageOf(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "No s’han pogut sincronitzar els canvis.";
}

async function runFlush(): Promise<void> {
  const entries = await listQueue();
  if (entries.length === 0) {
    setPending(0);
    return;
  }

  setSyncing(true);
  setLastError(null);

  let synced = false;
  let lastError: string | null = null;

  try {
    for (const entry of entries) {
      let res: Response;
      try {
        res = await authorizedFetch(entry.path, {
          method: entry.method,
          body: entry.body ?? undefined,
        });
      } catch (error) {
        if (isNetworkError(error)) {
          // Still offline: keep the entry and stop so FIFO order is preserved.
          await updateQueue({ ...entry, attempts: entry.attempts + 1 });
          lastError = error.message;
        } else {
          // Session/storage problem: stop without discarding the entry.
          lastError = messageOf(error);
        }
        break;
      }

      // Any HTTP response means the server saw the request. A 4xx is a real
      // rejection (track deleted, playlist gone…) and must not block the queue.
      await removeQueue(entry.id);
      if (res.ok) {
        synced = true;
      } else {
        lastError = (await parseError(res)).message;
      }
    }

    if (synced) {
      await clearCachedResponses(LIBRARY_CACHE_PREFIXES);
    }
  } finally {
    setPending(await countQueue());
    setSyncing(false);
    setLastError(lastError);
  }
}

/**
 * Replay queued mutations in creation order.
 *
 * Safe to call repeatedly: while a flush is running the same promise is
 * returned, and a second flush starts only after the first settles.
 */
export function flushQueue(): Promise<void> {
  if (flushing) return flushing;
  flushing = runFlush().finally(() => {
    flushing = null;
  });
  return flushing;
}
