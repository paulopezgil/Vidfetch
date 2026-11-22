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

/** Lifecycle of a playlist row (`playlists.status`). */
export type PlaylistStatus =
  | "pending"
  | "downloading"
  | "ready"
  | "partial"
  | "failed"
  | "cancelled";

/** Lifecycle of one item inside a playlist (`playlist_items.status`). */
export type PlaylistItemStatus =
  | "pending"
  | "downloading"
  | "ready"
  | "failed"
  | "cancelled";

/** One ready asset in the caller's library (`GET /api/library`). */
export interface LibraryItem {
  job_id: string;
  asset_id: string;
  title: string;
  file_size_bytes: number;
  output_ext: string;
  thumbnail_path: string | null;
  created_at: string;
  status: DownloadJobStatus;
  format_selector: string;
  /** Set when the asset was produced by a playlist item job. */
  playlist_id?: string | null;
}

/** Paginated response for `GET /api/library`. */
export interface LibraryList {
  items: LibraryItem[];
  total: number;
  limit: number;
  offset: number;
}

/** A playlist owned by the caller (`GET /api/playlists`). */
export interface PlaylistV2 {
  id: string;
  user_id: string;
  canonical_id: string;
  source_url: string;
  title: string;
  channel: string;
  thumbnail_path: string | null;
  /** Optional signed cover URL when the API can mint one for playlists. */
  thumbnail_url?: string | null;
  item_count: number;
  options_hash: string;
  format_selector: string;
  status: PlaylistStatus;
  created_at: string;
  updated_at: string;
}

/** A single video position inside a playlist. */
export interface PlaylistItemV2 {
  id: string;
  playlist_id: string;
  position: number;
  canonical_id: string;
  source_url: string;
  title: string;
  duration_seconds: number | null;
  asset_id: string | null;
  job_id: string | null;
  status: PlaylistItemStatus;
  error: string;
  /** Optional signed thumbnail URL when the API can mint one for items. */
  thumbnail_url?: string | null;
  created_at: string;
  updated_at: string;
}

/** `GET /api/playlists/{playlist_id}` — playlist plus its ordered items. */
export interface PlaylistDetailV2 extends PlaylistV2 {
  items: PlaylistItemV2[];
}

/** Paginated response for `GET /api/playlists`. */
export interface PlaylistList {
  items: PlaylistV2[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * Short-lived signed media URL (`POST /api/media/{asset_id}/token`).
 *
 * `url` streams the asset; `thumbnail_url` is `null` when the asset has no
 * thumbnail. Refresh before `expires_at` (or `expires_in` seconds) elapse.
 */
export interface MediaToken {
  token: string;
  url: string;
  thumbnail_url: string | null;
  expires_at: string;
  expires_in: number;
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
