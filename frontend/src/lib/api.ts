import type {
  AdminUser,
  AdminUserList,
  ApiErrorShape,
  AppRole,
  Profile,
} from "../types/auth";
import type {
  CreateDownloadPayload,
  DownloadJob,
  DownloadJobList,
  MediaInfo,
  MediaToken,
  PlaylistDetailV2,
  PlaylistList,
  PlaylistStatus,
  TrackList,
} from "../types/v2";
import { supabase, supabaseConfigError } from "./supabase";

/** Base URL for the v2 API. Same-origin `/api` by default. */
export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** Error carrying the API's stable `code` plus the HTTP status. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, status: number, code = "request_failed") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function buildUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const base = API_BASE.replace(/\/+$/, "");
  // Accept paths that already include the API base (for example the result of
  // `playlistZipUrl`) without prefixing it twice.
  if (base && (path === base || path.startsWith(`${base}/`))) return path;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * Absolute URL for an API-relative resource, such as the signed media and
 * thumbnail URLs returned by `POST /api/media/{id}/token`.
 *
 * The backend always answers with paths that start with `/api`, which is
 * correct when the frontend and API share an origin. When `VITE_API_BASE` is
 * absolute (Vercel frontend + separately hosted API), those paths must be
 * resolved against the API origin or the browser would request them from the
 * static frontend host. Absolute URLs and non-HTTP schemes are untouched.
 */
export function resolveApiUrl(path: string): string {
  if (/^[a-z][a-z0-9+.-]*:/i.test(path)) return path;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (/^https?:\/\//i.test(API_BASE)) {
    const base = `${API_BASE.replace(/\/+$/, "")}/`;
    return new URL(normalized, base).toString();
  }
  return normalized;
}

async function parseError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = res.statusText || `La petició ha fallat (${res.status}).`;

  const text = await res.text();
  if (text) {
    try {
      const body = JSON.parse(text) as Partial<ApiErrorShape> & {
        detail?: unknown;
        message?: unknown;
      };
      if (body.error?.code && body.error?.message) {
        code = body.error.code;
        message = body.error.message;
      } else if (typeof body.detail === "string") {
        message = body.detail;
      } else if (typeof body.message === "string") {
        message = body.message;
      }
    } catch {
      message = text;
    }
  }

  return new ApiError(message, res.status, code);
}

function authHeaders(init: RequestInit, token: string | null): Headers {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (
    init.body != null &&
    !(init.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }
  return headers;
}

function request(
  path: string,
  init: RequestInit,
  token: string | null,
): Promise<Response> {
  return fetch(buildUrl(path), { ...init, headers: authHeaders(init, token) });
}

async function readBody<T>(res: Response): Promise<T> {
  if (res.status === 204 || res.status === 205) return undefined as T;
  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return (await res.text()) as unknown as T;
  }
  return (await res.json()) as T;
}

/**
 * Authenticated fetch that returns the raw response.
 *
 * The current Supabase access token is attached automatically. A `401`
 * triggers exactly one session refresh and one retry.
 */
async function authorizedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  if (!supabase) {
    throw new ApiError(
      supabaseConfigError ?? "Supabase no està configurat.",
      0,
      "supabase_not_configured",
    );
  }

  const { data: current, error: sessionError } = await supabase.auth.getSession();
  if (sessionError) {
    throw new ApiError(sessionError.message, 0, "session_unavailable");
  }

  let res = await request(path, init, current.session?.access_token ?? null);

  if (res.status === 401) {
    const { data: refreshed, error: refreshError } =
      await supabase.auth.refreshSession();
    if (!refreshError && refreshed.session) {
      res = await request(path, init, refreshed.session.access_token);
    }
  }

  return res;
}

/**
 * Authenticated JSON fetch.
 *
 * Non-2xx responses are parsed into an `ApiError`.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await authorizedFetch(path, init);
  if (!res.ok) throw await parseError(res);
  return readBody<T>(res);
}

/** A binary response plus the filename suggested by the server, if any. */
export interface BlobDownload {
  blob: Blob;
  filename: string | null;
}

function filenameFromContentDisposition(value: string | null): string | null {
  if (!value) return null;

  const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(value);
  if (encoded?.[1]) {
    const candidate = encoded[1].trim();
    try {
      return decodeURIComponent(candidate);
    } catch {
      return candidate;
    }
  }

  const quoted =
    /filename\s*=\s*"([^"]+)"/i.exec(value) ??
    /filename\s*=\s*([^;]+)/i.exec(value);
  return quoted?.[1]?.trim() || null;
}

/** Authenticated binary fetch, used for on-demand archives and exports. */
export async function fetchBlob(
  path: string,
  init: RequestInit = {},
): Promise<BlobDownload> {
  const res = await authorizedFetch(path, init);
  if (!res.ok) throw await parseError(res);
  return {
    blob: await res.blob(),
    filename: filenameFromContentDisposition(
      res.headers.get("content-disposition"),
    ),
  };
}

/**
 * Append `download=1` to a signed media URL without breaking an existing
 * query string or fragment.
 */
export function withDownloadFlag(url: string): string {
  const hashIndex = url.indexOf("#");
  const hash = hashIndex >= 0 ? url.slice(hashIndex) : "";
  const base = hashIndex >= 0 ? url.slice(0, hashIndex) : url;
  const separator = base.includes("?")
    ? base.endsWith("?") || base.endsWith("&")
      ? ""
      : "&"
    : "?";
  return `${base}${separator}download=1${hash}`;
}

/** Start a browser download for an already-authorized media URL. */
export function triggerDownload(url: string, filename?: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  if (filename) anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 0);
}

/** `GET /api/me` — current profile, approval flag and app role. */
export function getMe(): Promise<Profile> {
  return apiFetch<Profile>("/me");
}

export interface AdminUserQuery {
  search?: string;
  approved?: boolean;
  role?: AppRole;
  limit?: number;
  offset?: number;
}

/** `GET /api/admin/users` — paginated user directory. */
export function listAdminUsers(
  params: AdminUserQuery = {},
): Promise<AdminUserList> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.approved !== undefined) {
    query.set("approved", String(params.approved));
  }
  if (params.role) query.set("role", params.role);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString();
  return apiFetch<Partial<AdminUserList> & { items?: AdminUser[] }>(
    `/admin/users${suffix ? `?${suffix}` : ""}`,
  ).then((raw) => {
    // Accept either `{ users }` or the `{ items }` pagination convention.
    const users = raw.users ?? raw.items ?? [];
    return {
      users,
      total: raw.total ?? users.length,
      limit: raw.limit ?? params.limit ?? users.length,
      offset: raw.offset ?? params.offset ?? 0,
    };
  });
}

/** `POST /api/admin/users/{id}/approve` */
export function approveUser(userId: string): Promise<AdminUser> {
  return apiFetch<AdminUser>(
    `/admin/users/${encodeURIComponent(userId)}/approve`,
    { method: "POST" },
  );
}

/** `POST /api/admin/users/{id}/revoke` */
export function revokeUser(userId: string): Promise<AdminUser> {
  return apiFetch<AdminUser>(
    `/admin/users/${encodeURIComponent(userId)}/revoke`,
    { method: "POST" },
  );
}

export interface DownloadQuery {
  status?: string;
  limit?: number;
  offset?: number;
}

/** `POST /api/info` — resolve video or playlist metadata before downloading. */
export function getInfo(url: string): Promise<MediaInfo> {
  return apiFetch<MediaInfo>("/info", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

/** `POST /api/downloads` — create an idempotent download job. */
export function createDownload(
  payload: CreateDownloadPayload,
): Promise<DownloadJob> {
  return apiFetch<DownloadJob>("/downloads", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** `GET /api/downloads` — list the caller's jobs, newest first. */
export function listDownloads(
  params: DownloadQuery = {},
): Promise<DownloadJobList> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString();
  return apiFetch<DownloadJobList>(`/downloads${suffix ? `?${suffix}` : ""}`);
}

/** `GET /api/downloads/{job_id}` — job detail and progress. */
export function getDownload(jobId: string): Promise<DownloadJob> {
  return apiFetch<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}`);
}

/** `POST /api/downloads/{job_id}/cancel` — request cancellation. */
export function cancelDownload(jobId: string): Promise<DownloadJob> {
  return apiFetch<DownloadJob>(
    `/downloads/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  );
}

export interface TrackQuery {
  limit?: number;
  offset?: number;
  /** Optional trimmed search over title, artist and album. */
  q?: string;
}

/** `GET /api/tracks` — the caller's ready tracks, newest first. */
export function listTracks(params: TrackQuery = {}): Promise<TrackList> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const q = params.q?.trim();
  if (q) query.set("q", q);
  const suffix = query.toString();
  return apiFetch<TrackList>(`/tracks${suffix ? `?${suffix}` : ""}`);
}

/** `DELETE /api/library/{job_id}` — remove one asset from the library. */
export function removeFromLibrary(jobId: string): Promise<void> {
  return apiFetch<void>(`/library/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
}

export interface PlaylistQuery {
  status?: PlaylistStatus;
  limit?: number;
  offset?: number;
}

/** `GET /api/playlists` — the caller's playlists, newest first. */
export function listPlaylists(
  params: PlaylistQuery = {},
): Promise<PlaylistList> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString();
  return apiFetch<PlaylistList>(`/playlists${suffix ? `?${suffix}` : ""}`);
}

/** `GET /api/playlists/{playlist_id}` — playlist detail plus items. */
export function getPlaylist(playlistId: string): Promise<PlaylistDetailV2> {
  return apiFetch<PlaylistDetailV2>(
    `/playlists/${encodeURIComponent(playlistId)}`,
  );
}

/** `DELETE /api/playlists/{playlist_id}` — remove the caller's playlist. */
export function deletePlaylist(playlistId: string): Promise<void> {
  return apiFetch<void>(`/playlists/${encodeURIComponent(playlistId)}`, {
    method: "DELETE",
  });
}

/** `POST /api/media/{asset_id}/token` — mint a short-lived signed URL. */
export async function getMediaToken(assetId: string): Promise<MediaToken> {
  const token = await apiFetch<MediaToken>(
    `/media/${encodeURIComponent(assetId)}/token`,
    { method: "POST" },
  );
  // The API returns `/api/...` paths. Resolve them against the API origin so
  // previews and downloads keep working when the frontend is hosted apart
  // from the API (absolute `VITE_API_BASE`).
  return {
    ...token,
    url: resolveApiUrl(token.url),
    thumbnail_url: token.thumbnail_url
      ? resolveApiUrl(token.thumbnail_url)
      : token.thumbnail_url,
  };
}

/** Stream URL for a playlist ZIP (`GET /api/playlists/{playlist_id}/zip`). */
export function playlistZipUrl(playlistId: string): string {
  return buildUrl(`/playlists/${encodeURIComponent(playlistId)}/zip`);
}

/**
 * Download a playlist ZIP through the authenticated API.
 *
 * The ZIP endpoint requires a bearer token, so a plain navigation to
 * `playlistZipUrl` would be rejected. Fetching it as a blob lets the normal
 * Supabase auth and 401-refresh flow apply before the browser saves the file.
 */
export async function downloadPlaylistZip(
  playlistId: string,
  fallbackName = "playlist.zip",
): Promise<void> {
  const { blob, filename } = await fetchBlob(
    `/playlists/${encodeURIComponent(playlistId)}/zip`,
  );
  triggerBlobDownload(blob, filename || fallbackName);
}
