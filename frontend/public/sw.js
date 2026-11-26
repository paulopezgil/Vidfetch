/*
 * Vidfetch offline app-shell service worker.
 *
 * Scope:
 *  - navigation requests: network-first, cached `/index.html` as offline fallback
 *  - built assets (`/assets/`): cache-first with a background refresh
 *  - images from any origin: cache-first with a background refresh, normalized
 *    to `origin + pathname` so signed tokens and CDN params can change
 *  - Google Fonts CSS and font files: cache-first
 *  - `/api/` and every non-GET request pass straight through unless the request
 *    is an image, so media tokens, auth and the download queue are untouched.
 *
 * Bump SHELL_CACHE when the shell strategy changes; only old shell caches are
 * dropped on activate. The media (`vidfetch-media-v1`), font and image caches
 * are managed through Cache Storage and survive shell upgrades.
 */

const SHELL_CACHE = "vidfetch-shell-v3";
const FONT_CACHE = "vidfetch-fonts-v1";
const IMAGE_CACHE = "vidfetch-images-v1";
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

/** Stable key shared with `src/offline/images.ts`. */
function imageCacheKey(url) {
  return `${url.origin}${url.pathname}`;
}

/**
 * Fetch and cache one image. Opaque cross-origin responses are valid entries,
 * and a failed cache write still returns the network response so the image
 * renders.
 */
function refreshImage(request) {
  return (async () => {
    try {
      const response = await fetch(request);
      if (response && (response.ok || response.type === "opaque")) {
        try {
          const url = new URL(request.url);
          const cache = await caches.open(IMAGE_CACHE);
          await cache.put(
            new Request(imageCacheKey(url), { mode: "no-cors" }),
            response.clone(),
          );
        } catch {
          // Defensive: one failed image must not break the request chain.
        }
      }
      return response;
    } catch {
      return null;
    }
  })();
}

/** Serve a cached image, falling back to the shell cache for static icons. */
async function serveImage(request, network) {
  try {
    const url = new URL(request.url);
    const cache = await caches.open(IMAGE_CACHE);
    const cached = await cache.match(imageCacheKey(url));
    if (cached) return cached;
  } catch {
    // Fall through to the network.
  }

  const fresh = await network;
  if (fresh) return fresh;

  try {
    const shell = await caches.open(SHELL_CACHE);
    const fallback = await shell.match(request, { ignoreSearch: true });
    if (fallback) return fallback;
  } catch {
    // No shell fallback available.
  }
  return Response.error();
}

/** Cache-first Google Fonts stylesheet or font file, including opaque entries. */
async function handleFont(request) {
  let cache = null;
  let cached = null;

  try {
    cache = await caches.open(FONT_CACHE);
    cached = await cache.match(request);
    // A CORS caller needs the readable CSS; an old opaque entry cannot be
    // parsed by the font prefetch, so refresh it instead of returning it.
    if (cached && !(cached.type === "opaque" && request.mode === "cors")) {
      return cached;
    }
  } catch {
    // Fall through to the network.
  }

  try {
    const response = await fetch(request);
    if (cache && response && (response.ok || response.type === "opaque")) {
      try {
        const key =
          response.type === "opaque"
            ? new Request(request.url, { mode: "no-cors" })
            : request;
        await cache.put(key, response.clone());
      } catch {
        // Defensive: a failed font cache write must not break rendering.
      }
    }
    return response;
  } catch {
    return cached || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Images first, for every origin: signed API thumbnails, covers and external
  // image hosts all need the same cache. Media (audio/video) is not an image.
  if (request.destination === "image") {
    const network = refreshImage(request);
    event.waitUntil(network);
    event.respondWith(serveImage(request, network));
    return;
  }

  // Google Fonts stylesheets and the font files they reference.
  if (
    url.hostname === "fonts.googleapis.com" ||
    url.hostname === "fonts.gstatic.com"
  ) {
    event.respondWith(handleFont(request));
    return;
  }

  if (url.origin !== self.location.origin) return;
  if (url.pathname === "/sw.js") return;
  // The API owns auth, tokens and the queue; never cache non-image responses.
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
