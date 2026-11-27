import type { DownloadFormat } from "../types/v2";

/**
 * Height caps the backend accepts, highest first.
 *
 * Playlists and single videos both use these caps; an odd source height such
 * as 576p is rounded down to a cap instead of being sent as-is.
 */
export const SUPPORTED_HEIGHTS = [
  2160, 1440, 1080, 720, 540, 480, 360, 240, 144,
] as const;

/** Caps offered for a whole playlist, where each item may differ. */
export const PLAYLIST_HEIGHTS = [
  2160, 1440, 1080, 720, 540, 480, 360,
] as const;

const HEIGHT_FORMATS = new Set<DownloadFormat>(
  SUPPORTED_HEIGHTS.map((height) => `${height}p` as DownloadFormat),
);

const DOWNLOAD_FORMATS = new Set<DownloadFormat>([
  "best",
  ...HEIGHT_FORMATS,
  "audio",
  "mp3",
]);

/** True for the profiles that only produce audio. */
export function isAudioFormat(format: DownloadFormat): boolean {
  return format === "audio" || format === "mp3";
}

/** True when a value is one of the profiles the backend accepts. */
export function isDownloadFormat(value: string): value is DownloadFormat {
  return DOWNLOAD_FORMATS.has(value as DownloadFormat);
}

/**
 * Read the profile from a stored selector.
 *
 * Jobs and playlists store the intent (`720p`, `audio`, optionally `+subs`).
 * Rows written by older versions can still hold a raw yt-dlp selector, so
 * those are recognised too. Unknown values fall back to `best`, which always
 * resolves.
 */
export function formatFromSelector(selector: string): DownloadFormat {
  const value = (selector ?? "").trim().toLowerCase();
  const intent = value.split("+")[0];
  if (isDownloadFormat(intent)) return intent;

  const heightMatch =
    value.match(/height\s*<=\s*(\d+)/) ?? value.match(/(\d{3,4})p\b/);
  if (heightMatch) {
    const height = Number(heightMatch[1]);
    if ((SUPPORTED_HEIGHTS as readonly number[]).includes(height)) {
      return `${height}p` as DownloadFormat;
    }
  }

  // Raw `bestvideo+bestaudio/best` is the full-quality profile; a bare
  // `bestaudio` selector was the old MP3 path.
  if (value.includes("bestvideo")) return "best";
  if (value.includes("bestaudio") || value.includes("mp3")) return "mp3";
  return "best";
}

/** Human label for a stored selector, used by jobs and library rows. */
export function formatLabel(selector: string): string {
  const format = formatFromSelector(selector);
  if (format === "audio") return "Àudio (millor)";
  if (format === "mp3") return "MP3 320";
  if (format === "best") return "Millor disponible";
  return `Vídeo · ${format}`;
}
