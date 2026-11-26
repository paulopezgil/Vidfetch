/*
 * Vidfetch offline app-shell service worker.
 *
 * Scope, deliberately narrow:
 *  - navigation requests: network-first, cached `/index.html` as offline fallback
 *  - built assets (`/assets/`): cache-first with a background refresh
 *  - same-origin GET only; `/api/` and every non-GET request pass straight
 *    through, so media tokens, auth and the download queue are untouched.
 *
 * Bump SHELL_CACHE when the caching strategy changes; old shell caches are
 * dropped on activate. The media cache (`vidfetch-media-v1`) is managed by the
 * app through Cache Storage and is never touched here.
 */

const SHELL_CACHE = "vidfetch-shell-v2";
const INDEX_KEY = "/index.html";

/**
 * Public static shell files served at the origin root. They are precached and
 * answered cache-first so the logo, manifest and installed-app icons are
 * available offline instead of failing as a broken image.
 */
const STATIC_SHELL = [
  "/favicon.svg",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-512.png",
  "/apple-touch-icon.png",
];
const STATIC_SHELL_PATHS = new Set(STATIC_SHELL);

const PRECACHE = [INDEX_KEY, ...STATIC_SHELL];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // Cache entries individually: one missing icon must not abort install.
      await Promise.allSettled(
        PRECACHE.map((url) => cache.add(new Request(url, { cache: "reload" }))),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(
            (key) => key.startsWith("vidfetch-shell-") && key !== SHELL_CACHE,
          )
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

/** Network-first navigation with the app shell as the offline fallback. */
async function handleNavigation(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      // Keep the newest document for offline navigations. Cache it under the
      // canonical `/index.html` key so deep links share one shell entry.
      const url = new URL(request.url);
      if (url.pathname === "/" || url.pathname.endsWith("/index.html")) {
        await cache.put(INDEX_KEY, response.clone());
      }
    }
    return response;
  } catch {
    const cached =
      (await cache.match(INDEX_KEY)) || (await cache.match("/"));
    if (cached) return cached;
    return new Response(
      "<!doctype html><meta charset=\"utf-8\"><title>Vidfetch</title><body style=\"font-family:Roboto,sans-serif;padding:2rem\"><h1>Sense connexió</h1><p>Torna-ho a provar quan recuperis la xarxa.</p></body>",
      {
        status: 503,
        statusText: "Offline",
        headers: { "Content-Type": "text/html; charset=utf-8" },
      },
    );
  }
}

/** Cache-first built asset with a background revalidation. */
async function handleAsset(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);

  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  if (cached) return cached;
  const fresh = await network;
  return fresh || Response.error();
}

/** Cache-first public shell file, so the brand assets survive offline. */
async function handleStaticShell(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request, { ignoreSearch: true });
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === "/sw.js") return;
  // The API owns auth, tokens and the queue; never cache it.
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(handleNavigation(request));
    return;
  }

  if (STATIC_SHELL_PATHS.has(url.pathname)) {
    event.respondWith(handleStaticShell(request));
    return;
  }

  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(handleAsset(request));
  }
});
