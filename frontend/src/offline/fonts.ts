/**
 * Local cache for the Google Fonts stylesheets and font files.
 *
 * `index.html` loads Roboto and Material Symbols Rounded from Google Fonts.
 * The service worker can replay those requests offline, but the cache is only
 * useful if the CSS and the actual font files are present, so this module warms
 * both after the first paint.
 *
 * Every helper fails closed: without Cache Storage, CORS or network access the
 * app keeps using the browser's normal font loading.
 */
export const FONT_CACHE_NAME = "vidfetch-fonts-v1";

/** Keep in sync with the Google Fonts `<link>` tags in `index.html`. */
const STYLESHEET_SELECTOR =
  'link[rel="stylesheet"][href*="fonts.googleapis.com"]';

/** Absolute font URLs inside the Google CSS (`@font-face` declarations). */
const FONT_URL_PATTERN = /url\(\s*(['"]?)(https?:\/\/[^'")]+)\1\s*\)/g;

let started: Promise<void> | null = null;

/** Store a response if it can be replayed; one bad entry never throws. */
async function putInCache(
  cache: Cache,
  url: string,
  response: Response,
): Promise<void> {
  try {
    if (!response.ok && response.type !== "opaque") return;
    if (response.type === "opaque") {
      // Opaque responses can only be stored under a no-cors request.
      await cache.put(
        new Request(url, { mode: "no-cors" }),
        response.clone(),
      );
      return;
    }
    await cache.put(url, response.clone());
  } catch {
    // Best effort: a failed font cache must never affect rendering.
  }
}

/** Absolute URLs referenced by `url(...)` in a stylesheet. */
function fontUrlsFromCss(css: string): string[] {
  const urls = new Set<string>();
  for (const match of css.matchAll(FONT_URL_PATTERN)) {
    const url = match[2];
    if (url) urls.add(url);
  }
  return [...urls];
}

/**
 * Read one stylesheet, caching it when needed, and return its font URLs.
 *
 * An opaque entry cannot be parsed, so a CORS copy is fetched instead when the
 * browser exposes one. Offline with only an opaque entry, the SW still serves
 * the CSS; this prefetch simply cannot discover new font files.
 */
async function cacheStylesheet(
  cache: Cache,
  href: string,
): Promise<string[]> {
  let response: Response | null = null;
  try {
    const cached = await cache.match(href, { ignoreVary: true });
    if (cached && cached.type !== "opaque") response = cached;
  } catch {
    // Fall through to the network.
  }

  if (!response) {
    try {
      const fresh = await fetch(href, {
        mode: "cors",
        credentials: "omit",
      });
      if (!fresh.ok && fresh.type !== "opaque") return [];
      await putInCache(cache, href, fresh);
      response = fresh;
    } catch {
      return [];
    }
  }

  if (!response || response.type === "opaque") return [];
  try {
    return fontUrlsFromCss(await response.text());
  } catch {
    return [];
  }
}

/** Cache one font file unless it is already present. */
async function cacheFont(cache: Cache, href: string): Promise<void> {
  try {
    if (await cache.match(href, { ignoreVary: true })) return;
    const response = await fetch(href, {
      mode: "cors",
      credentials: "omit",
    });
    if (!response.ok && response.type !== "opaque") return;
    await putInCache(cache, href, response);
  } catch {
    // Best effort.
  }
}

/**
 * Warm the font cache without blocking the first paint.
 *
 * Call after `load` in production. Repeated calls share the same promise.
 */
export function prefetchOfflineFonts(): Promise<void> {
  if (started) return started;

  started = (async () => {
    if (typeof caches === "undefined" || typeof document === "undefined") {
      return;
    }

    const stylesheets = Array.from(
      document.querySelectorAll<HTMLLinkElement>(STYLESHEET_SELECTOR),
    )
      .map((link) => link.href)
      .filter(Boolean);
    if (stylesheets.length === 0) return;

    const cache = await caches.open(FONT_CACHE_NAME);
    const fontUrls = new Set<string>();
    const results = await Promise.allSettled(
      stylesheets.map((href) => cacheStylesheet(cache, href)),
    );
    for (const result of results) {
      if (result.status === "fulfilled") {
        for (const url of result.value) fontUrls.add(url);
      }
    }

    await Promise.allSettled(
      [...fontUrls].map((href) => cacheFont(cache, href)),
    );
  })().catch(() => {
    // A failed warm-up leaves the browser's normal font loading in place.
  });

  return started;
}
