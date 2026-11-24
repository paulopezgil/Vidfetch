/**
 * IndexedDB-backed offline store.
 *
 * Two object stores:
 *  - `responses`: cacheable GET bodies, keyed by the normalized API path.
 *  - `queue`: mutations that failed on the network and await a replay.
 *
 * The module fails closed: when IndexedDB is unavailable (private mode,
 * blocked storage, older browser) every helper resolves to an empty/failed
 * result and the app keeps working as an online-only client.
 */

/** One cached JSON response body plus the time it was stored. */
export interface CachedResponse {
  body: unknown;
  savedAt: number;
}

/** One mutation waiting to be replayed against the API. */
export interface QueuedRequest {
  id: string;
  path: string;
  method: string;
  /** Serialized JSON request body, or `null` for bodyless requests. */
  body: string | null;
  createdAt: number;
  attempts: number;
}

/** Fields accepted by {@link enqueue}; the rest are generated locally. */
export type NewQueuedRequest = Pick<QueuedRequest, "path" | "method" | "body">;

const DB_NAME = "vidfetch-offline";
const DB_VERSION = 1;

/** Object store for cached GET responses. */
export const RESPONSES_STORE = "responses";
/** Object store for queued mutations. */
export const QUEUE_STORE = "queue";

let dbPromise: Promise<IDBDatabase | null> | null = null;

function openDatabase(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise<IDBDatabase | null>((resolve) => {
    if (typeof indexedDB === "undefined") {
      resolve(null);
      return;
    }

    let settled = false;
    const finish = (db: IDBDatabase | null) => {
      if (settled) return;
      settled = true;
      resolve(db);
    };

    try {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(RESPONSES_STORE)) {
          db.createObjectStore(RESPONSES_STORE);
        }
        if (!db.objectStoreNames.contains(QUEUE_STORE)) {
          db.createObjectStore(QUEUE_STORE, { keyPath: "id" });
        }
      };
      request.onsuccess = () => finish(request.result);
      request.onerror = () => finish(null);
      request.onblocked = () => finish(null);
    } catch {
      finish(null);
    }
  });

  return dbPromise;
}

function runRead<T>(
  storeName: string,
  operation: (store: IDBObjectStore) => IDBRequest,
): Promise<T | null> {
  return openDatabase()
    .then((db) => {
      if (!db) return null;
      return new Promise<T | null>((resolve) => {
        let result: T | null = null;
        try {
          const transaction = db.transaction(storeName, "readonly");
          const request = operation(transaction.objectStore(storeName));
          request.onsuccess = () => {
            result = (request.result as T) ?? null;
          };
          transaction.oncomplete = () => resolve(result);
          transaction.onerror = () => resolve(null);
          transaction.onabort = () => resolve(null);
        } catch {
          resolve(null);
        }
      });
    })
    .catch(() => null);
}

function runWrite(
  storeName: string,
  operation: (store: IDBObjectStore) => void,
): Promise<boolean> {
  return openDatabase()
    .then((db) => {
      if (!db) return false;
      return new Promise<boolean>((resolve) => {
        try {
          const transaction = db.transaction(storeName, "readwrite");
          operation(transaction.objectStore(storeName));
          transaction.oncomplete = () => resolve(true);
          transaction.onerror = () => resolve(false);
          transaction.onabort = () => resolve(false);
        } catch {
          resolve(false);
        }
      });
    })
    .catch(() => false);
}

function createId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `q-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Read a cached response, or `null` when missing/unavailable. */
export function readCache(key: string): Promise<CachedResponse | null> {
  return runRead<CachedResponse>(RESPONSES_STORE, (store) => store.get(key));
}

/** Store a response body. Resolves `false` when IndexedDB is unavailable. */
export function writeCache(
  key: string,
  body: unknown,
  savedAt = Date.now(),
): Promise<boolean> {
  return runWrite(RESPONSES_STORE, (store) => {
    store.put({ body, savedAt } satisfies CachedResponse, key);
  });
}

/** Remove one cached response. Resolves `false` on storage failure. */
export function deleteCache(key: string): Promise<boolean> {
  return runWrite(RESPONSES_STORE, (store) => {
    store.delete(key);
  });
}

/**
 * Drop cached responses whose key matches one of the given path prefixes.
 *
 * `/tracks` matches `/tracks` and `/tracks?…`, `/tracks/artists?…` but never
 * the unrelated `/tracks-foo`.
 */
export function clearCachedResponses(prefixes: string[]): Promise<boolean> {
  return runRead<IDBValidKey[]>(RESPONSES_STORE, (store) => store.getAllKeys())
    .then((keys) => {
      if (!keys || keys.length === 0) return false;
      const matches = keys.filter(
        (key): key is string =>
          typeof key === "string" &&
          prefixes.some(
            (prefix) =>
              key === prefix ||
              key.startsWith(`${prefix}?`) ||
              key.startsWith(`${prefix}/`),
          ),
      );
      if (matches.length === 0) return false;
      return runWrite(RESPONSES_STORE, (store) => {
        for (const key of matches) store.delete(key);
      });
    })
    .catch(() => false);
}

/** Append a mutation to the replay queue. `null` means it was not stored. */
export async function enqueue(
  request: NewQueuedRequest,
): Promise<QueuedRequest | null> {
  const entry: QueuedRequest = {
    id: createId(),
    path: request.path,
    method: request.method,
    body: request.body,
    createdAt: Date.now(),
    attempts: 0,
  };
  const stored = await runWrite(QUEUE_STORE, (store) => {
    store.add(entry);
  });
  return stored ? entry : null;
}

/** Every queued mutation, oldest first. */
export function listQueue(): Promise<QueuedRequest[]> {
  return runRead<QueuedRequest[]>(QUEUE_STORE, (store) => store.getAll())
    .then((entries) =>
      (entries ?? []).sort(
        (a, b) => a.createdAt - b.createdAt || a.id.localeCompare(b.id),
      ),
    )
    .catch(() => []);
}

/** Remove a replayed (or permanently rejected) mutation. */
export function removeQueue(id: string): Promise<boolean> {
  return runWrite(QUEUE_STORE, (store) => {
    store.delete(id);
  });
}

/** Rewrite one queued mutation, used to bump its attempt counter. */
export function updateQueue(entry: QueuedRequest): Promise<boolean> {
  return runWrite(QUEUE_STORE, (store) => {
    store.put(entry);
  });
}

/** Drop every queued mutation. */
export function clearQueue(): Promise<boolean> {
  return runWrite(QUEUE_STORE, (store) => {
    store.clear();
  });
}

/** Number of mutations waiting for a replay. */
export function countQueue(): Promise<number> {
  return runRead<number>(QUEUE_STORE, (store) => store.count())
    .then((count) => count ?? 0)
    .catch(() => 0);
}
