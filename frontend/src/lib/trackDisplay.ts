import type { Track } from "../types/v2";

/** Media kind derived from the stored output extension. */
export type MediaType = "video" | "audio" | "image";

const AUDIO_EXTENSIONS = new Set([
  "mp3",
  "m4a",
  "aac",
  "wav",
  "flac",
  "ogg",
  "opus",
]);

const IMAGE_EXTENSIONS = new Set([
  "jpg",
  "jpeg",
  "png",
  "webp",
  "gif",
  "avif",
  "bmp",
]);

/** Lowercase extension without the leading dot. */
export function extensionOf(item: Track): string {
  return (item.output_ext ?? "").replace(/^\./, "").toLowerCase();
}

export function mediaTypeFor(item: Track): MediaType {
  const ext = extensionOf(item);
  if (AUDIO_EXTENSIONS.has(ext)) return "audio";
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  return "video";
}

/** Material Symbols name for a track's placeholder thumbnail. */
export function trackIcon(item: Track): string {
  const type = mediaTypeFor(item);
  return type === "audio" ? "music_note" : type === "image" ? "image" : "movie";
}

/** Local calendar-day key (`YYYY-MM-DD`) used to group tracks. */
function localDayKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function localDayLabel(date: Date): string {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const key = localDayKey(date);
  if (key === localDayKey(now)) return "Avui";
  if (key === localDayKey(yesterday)) return "Ahir";
  return date.toLocaleDateString("ca-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

export interface TrackDay {
  key: string;
  label: string;
  items: Track[];
}

/** Group tracks by the local day of `downloaded_at`, newest day first. */
export function groupTracksByDay(items: Track[]): TrackDay[] {
  const stampOf = (item: Track) => {
    const time = Date.parse(item.downloaded_at);
    return Number.isFinite(time) ? time : 0;
  };
  const groups = new Map<string, TrackDay>();
  for (const item of [...items].sort((a, b) => stampOf(b) - stampOf(a))) {
    const date = new Date(item.downloaded_at);
    const valid = !Number.isNaN(date.getTime());
    const key = valid ? localDayKey(date) : "unknown";
    const group = groups.get(key);
    if (group) {
      group.items.push(item);
    } else {
      groups.set(key, {
        key,
        label: valid ? localDayLabel(date) : "Sense data",
        items: [item],
      });
    }
  }
  return Array.from(groups.values());
}
