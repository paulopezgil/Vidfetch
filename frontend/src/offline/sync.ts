import { authorizedFetch, isNetworkError, parseError } from "../lib/api";
import { getToken } from "../lib/session";
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

/**
 * Bumped whenever the queue is abandoned (sign-out). A flush that started
 * before the bump must stop touching the store and the banner: its entries
 * belong to the account that queued them, so finishing would resurrect them
 * for whoever signs in next.
 */
let flushGeneration = 0;

function messageOf(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "No s’han pogut sincronitzar els canvis.";
}

function isCurrent(generation: number): boolean {
  return generation === flushGeneration;
}

async function runFlush(generation: number): Promise<void> {
  const entries = await listQueue();
  if (!isCurrent(generation)) return;
  if (entries.length === 0) {
    setPending(0);
    return;
  }

  // Signed out: replaying anonymously would be rejected with a 401 and the
  // entries would be discarded. Keep them for the next sign-in instead.
  if (!getToken()) {
    setPending(entries.length);
    return;
  }

  setSyncing(true);
  setLastError(null);

  let synced = false;
  let lastError: string | null = null;

  try {
    for (const entry of entries) {
      if (!isCurrent(generation)) return;

      let res: Response;
      try {
        res = await authorizedFetch(entry.path, {
          method: entry.method,
          body: entry.body ?? undefined,
        });
      } catch (error) {
        if (!isCurrent(generation)) return;
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

      // A rejected session is not a rejection of the mutation itself. Keep the
      // entry and stop: `authorizedFetch` has already cleared the token, and the
      // same account must be able to sign back in and replay these edits.
      if (res.status === 401) {
        lastError = (await parseError(res)).message;
        break;
      }

      // Any other HTTP response means the server saw the request. A 4xx is a
      // real rejection (track deleted, playlist gone…) and must not block the
      // queue.
      if (!isCurrent(generation)) return;
      await removeQueue(entry.id);
      if (res.ok) {
        synced = true;
      } else {
        lastError = (await parseError(res)).message;
      }
    }

    if (synced && isCurrent(generation)) {
      await clearCachedResponses(LIBRARY_CACHE_PREFIXES);
    }
  } finally {
    if (isCurrent(generation)) {
      setPending(await countQueue());
      setSyncing(false);
      setLastError(lastError);
    }
  }
}

/**
 * Invalidate any in-flight replay and forget it.
 *
 * Called on sign-out: the queue is about to be cleared, so a flush that is
 * waiting on the network must not write an entry back or re-arm the banner for
 * the next account. Already-sent requests cannot be cancelled; they simply
 * finish without touching local state.
 */
export function resetQueueFlush(): void {
  flushGeneration += 1;
  flushing = null;
}

/**
 * Replay queued mutations in creation order.
 *
 * Safe to call repeatedly: while a flush is running the same promise is
 * returned, and a second flush starts only after the first settles.
 */
export function flushQueue(): Promise<void> {
  if (flushing) return flushing;
  const generation = flushGeneration;
  const run = runFlush(generation).finally(() => {
    // A sign-out may already have replaced this run; never drop the new one.
    if (flushing === run) flushing = null;
  });
  flushing = run;
  return run;
}
