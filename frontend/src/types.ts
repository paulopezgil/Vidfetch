export type OperationType = "video" | "playlist" | "playlist_item";
export type FormatName = "best" | "720p" | "mp3";

export type TaskStatus =
  | "queued"
  | "fetching information"
  | "downloading"
  | "processing"
  | "completed"
  | "failed"
  | "cancelled";

export interface VideoFormats {
  heights: number[];
  has_720p: boolean;
  has_audio: boolean;
}

export interface InfoEntry {
  id?: string;
  title?: string;
  url?: string;
  duration?: number | null;
  thumbnail?: string | null;
}

export interface InfoResult {
  type: "video" | "playlist";
  id?: string;
  title: string;
  channel?: string;
  thumbnail?: string | null;
  duration?: number | null;
  formats?: VideoFormats;
  video_count?: number;
  entries?: InfoEntry[];
  ext?: string;
  webpage_url?: string;
}

export interface Task {
  task_id: string;
  url: string;
  title: string;
  video_id?: string;
  operation_type: OperationType;
  format: FormatName;
  embed_subs: boolean;
  status: TaskStatus;
  progress: number;
  current_item_progress: number;
  downloaded_bytes: number;
  total_bytes: number;
  speed: number;
  eta: number;
  item_index: number;
  item_count: number;
  completed_items: number;
  current_item_title: string;
  playlist_id: string;
  output_filename: string;
  error: string;
  created_at: string;
  updated_at: string;
  completed_at: string;
}

export interface LibraryFile {
  filename: string;
  title: string;
  size: number;
  mtime: number;
  ext: string;
  media_type: "video" | "audio" | "image";
  thumbnail_url?: string | null;
  video_id?: string;
  playlist_id?: string;
}

export interface Playlist {
  playlist_id: string;
  url: string;
  title: string;
  channel?: string;
  thumbnail_url?: string | null;
  item_count: number;
  total_size: number;
  downloaded_count: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PlaylistItem {
  index: number;
  video_id: string;
  url: string;
  title: string;
  duration?: number | null;
  status: string;
  filename: string;
  size: number;
  error: string;
}

export interface PlaylistDetail extends Playlist {
  items: PlaylistItem[];
  failed_count: number;
}

export interface HistoryEntry extends Task {
  file_exists: boolean;
}

export interface HistoryPage {
  items: HistoryEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface LibraryResponse {
  files: LibraryFile[];
  playlists: Playlist[];
}

export interface Health {
  status: string;
  version: string;
  ytdlp_version?: string | null;
  python_version: string;
  dependencies: {
    node_available: boolean;
    node_version?: string | null;
    ffmpeg_available: boolean;
    ffmpeg_version?: string | null;
  };
}
