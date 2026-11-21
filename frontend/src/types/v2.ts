/** Compact format capabilities returned by `POST /api/info`. */
export interface MediaFormats {
  heights: number[];
  has_720p: boolean;
  has_audio: boolean;
}

/** A flat playlist entry returned by `POST /api/info`. */
export interface InfoEntry {
  id?: string;
  title?: string;
  url?: string;
  duration?: number | null;
  thumbnail?: string | null;
}

/** Normalised metadata for a video or playlist (`POST /api/info`). */
export interface MediaInfo {
  type: "video" | "playlist";
  id?: string;
  canonical_id?: string;
  extractor_key?: string;
  title: string;
  channel?: string;
  duration?: number | null;
  thumbnail?: string | null;
  formats?: MediaFormats;
  video_count?: number;
  item_count?: number;
  truncated?: boolean;
  entries?: InfoEntry[];
  ext?: string;
  webpage_url?: string;
}

/** Lifecycle of a v2 download job. */
export type DownloadJobStatus =
  | "queued"
  | "resolving"
  | "downloading"
  | "processing"
  | "ready"
  | "failed"
  | "cancelled";

/** Playlist jobs spawn per-video `playlist_item` jobs. */
export type DownloadJobKind = "video" | "playlist" | "playlist_item";

/** A per-user download job / history entry (`DownloadJobOut`). */
export interface DownloadJob {
  id: string;
  user_id: string;
  asset_id: string | null;
  playlist_id: string | null;
  kind: DownloadJobKind;
  source_url: string;
  title: string;
  options_hash: string;
  format_selector: string;
  status: DownloadJobStatus;
  progress: number;
  downloaded_bytes: number;
  total_bytes: number;
  speed: number;
  eta_seconds: number | null;
  error: string;
  attempts: number;
  cancel_requested: boolean;
  item_index: number;
  item_count: number;
  current_item_title: string;
  current_item_progress: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

/** Paginated response for `GET /api/downloads`. */
export interface DownloadJobList {
  items: DownloadJob[];
  total: number;
  limit: number;
  offset: number;
}

export type DownloadFormat = "best" | "720p" | "mp3";

/** Request body for `POST /api/downloads`. */
export interface CreateDownloadPayload {
  url: string;
  kind?: "video" | "playlist";
  format?: DownloadFormat;
  embed_subs?: boolean;
  playlist_id?: string;
  idempotency_key?: string;
}

const ACTIVE_STATUSES: ReadonlySet<DownloadJobStatus> = new Set([
  "queued",
  "resolving",
  "downloading",
  "processing",
]);

/** Whether a job is still in flight (non-terminal). */
export function isActiveJob(status: DownloadJobStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}
