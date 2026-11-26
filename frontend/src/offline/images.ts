import { useEffect } from "react";

/**
 * Local image cache.
 *
 * Thumbnails and covers are served from short-lived signed URLs and external
 * image hosts, so their query strings change even when the image does not.
 * Entries are therefore keyed by `origin + pathname`, which keeps cached artwork
 * usable offline across token and CDN parameter changes.
 *
 * Every helper fails closed: without Cache Storage the app keeps rendering
 * images online exactly as before.
 */
export const IMAGE_CACHE_NAME = "vidfetch-images-v1";

/** Stable Cache Storage key: the URL without its query or fragment. */
export function imageCacheKey(url: URL | string): string {
  const parsed =
    typeof url === "string" ? new URL(url, window.location.href) : url;
  return `${parsed.origin}${parsed.pathname}`;
}

const known = new Set<string>();
const inFlight = new Map<string, Promise<void>>();

/**
 * Cache one image for offline rendering, best effort.
 *
 * Non-HTTP(S) URLs (data, blob) are ignored. Concurrent calls for the same
 * normalized key share one request, and already-cached keys are skipped.
 * Signed and cross-origin images are fetched with `no-cors` so an opaque
 * response can still be stored and replayed offline.
 */
export function cacheImageUrl(src: string | null | undefined): Promise<void> {
  if (!src) return Promise.resolve();

  let url: URL;
  try {
    url = new URL(src, window.location.href);
  } catch {
    return Promise.resolve();
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return Promise.resolve();
  }

  const key = imageCacheKey(url);
  if (known.has(key)) return Promise.resolve();
  const running = inFlight.get(key);
  if (running) return running;

  const promise = (async () => {
    try {
      if (typeof caches === "undefined") return;
      const cache = await caches.open(IMAGE_CACHE_NAME);
      if (await cache.match(key)) {
        known.add(key);
        return;
      }

      const response = await fetch(url.toString(), {
        mode: "no-cors",
        credentials: "omit",
      });
      if (response.ok || response.type === "opaque") {
        await cache.put(
          new Request(key, { mode: "no-cors" }),
          response,
        );
        known.add(key);
      }
    } catch {
      // A failed image cache must never affect rendering or a media transfer.
    } finally {
      inFlight.delete(key);
    }
  })();

  inFlight.set(key, promise);
  return promise;
}

/** Cache an image without blocking its render. */
export function useImageCache(src: string | null | undefined): void {
  useEffect(() => {
    void cacheImageUrl(src);
  }, [src]);
}
