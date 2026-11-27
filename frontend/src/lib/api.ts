import type {
  AdminUser,
  AdminUserList,
  ApiErrorShape,
  AppRole,
  AuthSession,
  Profile,
} from "../types/auth";
import type {
  CreateDownloadPayload,
  DownloadJob,
  DownloadJobList,
  FacetList,
  MediaInfo,
  MediaToken,
  PlaylistDetailV2,
  PlaylistList,
  PlaylistStatus,
  Track,
  TrackList,
  TrackUpdate,
  UserPlaylist,
  UserPlaylistDetail,
  UserPlaylistInput,
  UserPlaylistList,
  UserPlaylistShare,
  UserPlaylistShareList,
} from "../types/v2";
import { clearToken, getToken, notifyUnauthorized } from "./session";
import {
  MAX_QUEUED_MUTATIONS,
  countQueue,
  enqueue,
  readCache,
  writeCache,
} from "../offline/db";
import {
  QUEUED_MUTATION_MESSAGE,
  isOffline,
  markCacheServed,
  reportNetworkFailure,
  reportNetworkSuccess,
  setPending,
} from "../offline/status";

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

/**
 * True when the request never reached the API (offline, DNS failure, CORS,
 * connection reset). Real HTTP error responses are never classified this way.
 */
export function isNetworkError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === "network_error";
}

function networkError(): ApiError {
  return new ApiError(
    "No hi ha connexió amb el servidor.",
    0,
    "network_error",
  );
}

function offlineUnavailable(): ApiError {
  return new ApiError(
    "Aquesta acció necessita connexió. Torna-ho a provar quan recuperis la xarxa.",
    0,
    "offline_unavailable",
  );
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

export async function parseError(res: Response): Promise<ApiError> {
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

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

async function request(
  path: string,
  init: RequestInit,
  token: string | null,
): Promise<Response> {
  try {
    return await fetch(buildUrl(path), {
      ...init,
      headers: authHeaders(init, token),
    });
  } catch (error) {
    // Aborts are intentional cancellations, not a lost connection.
    if (isAbortError(error)) throw error;
    throw networkError();
  }
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
 * The stored opaque session token is attached automatically. A `401` means the
 * server no longer accepts that token: it is forgotten and the unauthorized
 * event is emitted so the app can return to the login page. There is no refresh
 * step — the user signs in again. Transport failures are wrapped in an
 * `ApiError` with `status: 0` / `code: "network_error"` so callers can tell
 * “offline” apart from a real HTTP error.
 *
 * The body of a rejected response is left untouched so callers can still parse
 * the server's `error.code`.
 */
export async function authorizedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = getToken();

  let res: Response;
  try {
    res = await request(path, init, token);
  } catch (error) {
    if (isNetworkError(error)) reportNetworkFailure(error.message);
    throw error;
  }
  reportNetworkSuccess();

  if (res.status === 401 && token) {
    clearToken();
    notifyUnauthorized();
  }

  return res;
}

/**
 * Normalized cache key for a GET path: trailing slashes dropped and query
 * parameters sorted so equivalent requests share one entry.
 */
export function normalizeCacheKey(path: string): string {
  const withoutHash = path.split("#")[0] ?? path;
  const question = withoutHash.indexOf("?");
  const rawPath = question >= 0 ? withoutHash.slice(0, question) : withoutHash;
  const rawQuery = question >= 0 ? withoutHash.slice(question + 1) : "";
  const cleanPath = rawPath.replace(/\/+$/, "") || "/";

  const params = new URLSearchParams(rawQuery);
  const sorted = [...params.entries()].sort(
    ([a, av], [b, bv]) => a.localeCompare(b) || av.localeCompare(bv),
  );
  if (sorted.length === 0) return cleanPath;

  const query = new URLSearchParams();
  for (const [key, value] of sorted) query.append(key, value);
  return `${cleanPath}?${query.toString()}`;
}

/**
 * Media tokens, admin listings and binary downloads are never cached: they are
 * short-lived or authorization-sensitive.
 */
const CACHEABLE_GET_PATHS: readonly RegExp[] = [
  /^\/tracks$/,
  /^\/tracks\/(?:artists|albums)$/,
  /^\/playlists$/,
  /^\/playlists\/[^/]+$/,
  /^\/user-playlists$/,
  /^\/user-playlists\/[^/]+$/,
];

function isCacheableGet(path: string, method: string): boolean {
  if (method !== "GET") return false;
  const cleanPath = normalizeCacheKey(path).split("?")[0] ?? "";
  return CACHEABLE_GET_PATHS.some((pattern) => pattern.test(cleanPath));
}

/**
 * Authenticated JSON fetch.
 *
 * Cacheable GETs are network-first: a successful response is copied to the
 * local read cache, and a transport failure falls back to the cached body when
 * one exists. Non-2xx responses are parsed into an `ApiError` and never cached.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const cacheable = isCacheableGet(path, method)
    ? normalizeCacheKey(path)
    : null;

  let res: Response;
  try {
    res = await authorizedFetch(path, init);
  } catch (error) {
    if (cacheable && isNetworkError(error)) {
      const cached = await readCache(cacheable);
      if (cached) {
        markCacheServed(cached.savedAt);
        return cached.body as T;
      }
    }
    throw error;
  }

  if (!res.ok) throw await parseError(res);

  const body = await readBody<T>(res);
  if (cacheable) {
    void writeCache(cacheable, body);
  }
  return body;
}

/**
 * Marker returned when a mutation was stored locally instead of sent: the API
 * has not been updated yet and will receive the request when the connection
 * returns.
 */
export interface QueuedMutationResult {
  queued: true;
  /** User-facing copy shared by every queued mutation. */
  message: string;
}

/** Outcome of a mutation that may be replayed later. */
export type MutationResult<T> =
  | { queued: false; data: T }
  | QueuedMutationResult;

/**
 * Upper bound for a serialized queued body. Cover uploads are base64 JSON and
 * a 5 MiB image encodes to roughly 6.7 MiB, so this leaves some headroom.
 */
const MAX_QUEUED_BODY_CHARS = 8 * 1024 * 1024;

/** Shown when the offline mutation queue already holds its maximum entries. */
export const OFFLINE_QUEUE_FULL_MESSAGE =
  "La cua sense connexió és plena (200 canvis). Connecta’t per sincronitzar els canvis abans d’afegir-ne més.";

/**
 * Run a mutation, storing it in the offline queue when the network is down.
 *
 * Only transport failures are queued: HTTP errors are real answers from the
 * server and are rethrown untouched. When IndexedDB refuses the entry the
 * original network error is rethrown instead of pretending the change is safe.
 * A full queue is rejected with an explicit `ApiError`, never by dropping the
 * new mutation silently.
 */
export async function apiMutation<T>(
  path: string,
  init: RequestInit = {},
  options: { queueable?: boolean } = {},
): Promise<MutationResult<T>> {
  try {
    const data = await apiFetch<T>(path, init);
    return { queued: false, data };
  } catch (error) {
    if (!isNetworkError(error) || options.queueable === false) throw error;

    const rawBody = init.body;
    if (rawBody != null && typeof rawBody !== "string") throw error;
    if (rawBody != null && rawBody.length > MAX_QUEUED_BODY_CHARS) throw error;

    const pending = await countQueue();
    setPending(pending);
    if (pending >= MAX_QUEUED_MUTATIONS) {
      throw new ApiError(
        OFFLINE_QUEUE_FULL_MESSAGE,
        0,
        "offline_queue_full",
      );
    }

    const entry = await enqueue({
      path,
      method: (init.method ?? "POST").toUpperCase(),
      body: rawBody ?? null,
    });
    if (!entry) throw error;

    setPending(await countQueue());
    return { queued: true, message: QUEUED_MUTATION_MESSAGE };
  }
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

/** Largest cover art the API accepts, enforced here before reading the file. */
export const MAX_COVER_BYTES = 5 * 1024 * 1024;

/** Cover formats accepted by `POST /api/tracks/{track_id}/cover`. */
export const COVER_CONTENT_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

/**
 * Resolve the signed cover and asset-thumbnail URLs against the API origin
 * when they are relative.
 */
function resolveTrackCover(track: Track): Track {
  const cover = track.cover_url;
  const thumbnail = track.thumbnail_url;
  const resolvedCover = cover ? resolveApiUrl(cover) : cover;
  const resolvedThumbnail = thumbnail ? resolveApiUrl(thumbnail) : thumbnail;
  if (
    resolvedCover === cover &&
    resolvedThumbnail === thumbnail
  ) {
    return track;
  }
  return {
    ...track,
    ...(resolvedCover !== cover ? { cover_url: resolvedCover } : {}),
    ...(resolvedThumbnail !== thumbnail
      ? { thumbnail_url: resolvedThumbnail }
      : {}),
  };
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

/**
 * Unauthenticated JSON POST used by the sign-in endpoints.
 *
 * They must not go through `authorizedFetch`: a stale token would make a failed
 * sign-in look like an expired session and fire the unauthorized event.
 */
async function authPost<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    const failure = networkError();
    reportNetworkFailure(failure.message);
    throw failure;
  }
  reportNetworkSuccess();
  if (!res.ok) throw await parseError(res);
  return readBody<T>(res);
}

/** `POST /api/auth/login` — exchange email/password for a session token. */
export function login(email: string, password: string): Promise<AuthSession> {
  return authPost<AuthSession>("/auth/login", { email, password });
}

/** `POST /api/auth/register` — create an unapproved account and sign in. */
export function register(email: string, password: string): Promise<AuthSession> {
  return authPost<AuthSession>("/auth/register", { email, password });
}

/**
 * `POST /api/auth/logout` — revoke the current server session.
 *
 * Only the current token is revoked; a `401` means it was already gone and is
 * treated as success. Transport failures are rethrown so the caller can decide
 * whether the sign-out still proceeds locally.
 */
export async function logout(): Promise<void> {
  const token = getToken();
  if (!token) return;

  let res: Response;
  try {
    res = await request("/auth/logout", { method: "POST" }, token);
  } catch (error) {
    if (isNetworkError(error)) reportNetworkFailure(error.message);
    throw error;
  }
  reportNetworkSuccess();

  if (!res.ok && res.status !== 401) throw await parseError(res);
}

/** `POST /api/auth/password` — change the current account's password. */
export function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  return apiFetch<void>("/auth/password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
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

/**
 * `POST /api/admin/users/{id}/password` — reset another account's password.
 *
 * The backend revokes every session for the target user. Admin actions are
 * online-only, matching approve/revoke.
 */
export function resetUserPassword(
  userId: string,
  password: string,
): Promise<void> {
  return apiFetch<void>(
    `/admin/users/${encodeURIComponent(userId)}/password`,
    {
      method: "POST",
      body: JSON.stringify({ password }),
    },
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
  /** Server-side order: newest download first, or title A–Z. */
  sort?: "downloaded" | "title";
  /** Restrict the page to one media kind. */
  kind?: "audio" | "video" | "image";
}

/** `GET /api/tracks` — the caller's ready tracks, newest first by default. */
export function listTracks(params: TrackQuery = {}): Promise<TrackList> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const q = params.q?.trim();
  if (q) query.set("q", q);
  if (params.sort) query.set("sort", params.sort);
  if (params.kind) query.set("kind", params.kind);
  const suffix = query.toString();
  return apiFetch<TrackList>(
    `/tracks${suffix ? `?${suffix}` : ""}`,
  ).then((page) => ({ ...page, items: page.items.map(resolveTrackCover) }));
}

/**
 * `PATCH /api/tracks/{track_id}` — override the track's editable metadata.
 *
 * Empty strings clear an override, restoring the original job metadata.
 */
export async function updateTrack(
  trackId: string,
  payload: TrackUpdate,
): Promise<MutationResult<Track>> {
  const result = await apiMutation<Track>(
    `/tracks/${encodeURIComponent(trackId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
  return result.queued
    ? result
    : { queued: false, data: resolveTrackCover(result.data) };
}

function listFacets(path: string, q?: string, limit = 20): Promise<FacetList> {
  const query = new URLSearchParams();
  const term = q?.trim();
  if (term) query.set("q", term);
  query.set("limit", String(limit));
  return apiFetch<FacetList>(`${path}?${query.toString()}`);
}

/** `GET /api/tracks/artists` — artist suggestions with track counts. */
export function listArtistFacets(q?: string, limit = 20): Promise<FacetList> {
  return listFacets("/tracks/artists", q, limit);
}

/** `GET /api/tracks/albums` — album suggestions with track counts. */
export function listAlbumFacets(q?: string, limit = 20): Promise<FacetList> {
  return listFacets("/tracks/albums", q, limit);
}

/** Signed cover descriptor returned after an upload. */
export interface TrackCover {
  cover_path: string | null;
  cover_url: string | null;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else {
        reject(
          new ApiError(
            "No s’ha pogut llegir la imatge.",
            0,
            "cover_read_failed",
          ),
        );
      }
    };
    reader.onerror = () =>
      reject(
        new ApiError(
          "No s’ha pogut llegir la imatge.",
          0,
          "cover_read_failed",
        ),
      );
    reader.readAsDataURL(file);
  });
}

/**
 * `POST /api/tracks/{track_id}/cover` — replace a track's cover art.
 *
 * The API takes JSON (`content_type` plus base64 `data`), so the file is read
 * as a data URL. Size and MIME type are checked before reading to fail fast.
 */
export async function uploadTrackCover(
  trackId: string,
  file: File,
): Promise<MutationResult<TrackCover>> {
  if (file.size > MAX_COVER_BYTES) {
    throw new ApiError(
      "La imatge supera el límit de 5 MiB.",
      0,
      "cover_too_large",
    );
  }
  if (!(COVER_CONTENT_TYPES as readonly string[]).includes(file.type)) {
    throw new ApiError(
      "Format no admès. Fes servir JPEG, PNG o WebP.",
      0,
      "cover_type_unsupported",
    );
  }

  const dataUrl = await readFileAsDataUrl(file);
  const comma = dataUrl.indexOf(",");
  const match = /^data:([^;]+);base64$/.exec(dataUrl.slice(0, comma));
  const contentType = match?.[1] ?? file.type;
  const data = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;

  const result = await apiMutation<TrackCover>(
    `/tracks/${encodeURIComponent(trackId)}/cover`,
    {
      method: "POST",
      body: JSON.stringify({ content_type: contentType, data }),
    },
  );
  if (result.queued) return result;
  return {
    queued: false,
    data: {
      ...result.data,
      cover_url: result.data.cover_url
        ? resolveApiUrl(result.data.cover_url)
        : null,
    },
  };
}

/** `DELETE /api/tracks/{track_id}/cover` — remove the custom cover art. */
export function deleteTrackCover(trackId: string): Promise<MutationResult<void>> {
  return apiMutation<void>(`/tracks/${encodeURIComponent(trackId)}/cover`, {
    method: "DELETE",
  });
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

export interface UserPlaylistQuery {
  limit?: number;
  offset?: number;
}

/** Resolve signed cover URLs for every track in a curated playlist. */
function resolveUserPlaylistDetail(
  detail: UserPlaylistDetail,
): UserPlaylistDetail {
  return { ...detail, items: detail.items.map(resolveTrackCover) };
}

/** `GET /api/user-playlists` — the caller's curated playlists. */
export function listUserPlaylists(
  params: UserPlaylistQuery = {},
): Promise<UserPlaylistList> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString();
  return apiFetch<UserPlaylistList>(
    `/user-playlists${suffix ? `?${suffix}` : ""}`,
  );
}

/**
 * `GET /api/user-playlists/shared` — curated playlists other users shared with
 * the caller. Every entry has `is_owner: false` and the owner's email, and the
 * detail view exposes the owner's visible tracks read-only.
 */
export function listSharedUserPlaylists(
  params: UserPlaylistQuery = {},
): Promise<UserPlaylistList> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString();
  return apiFetch<UserPlaylistList>(
    `/user-playlists/shared${suffix ? `?${suffix}` : ""}`,
  );
}

/** `GET /api/user-playlists/{playlist_id}/shares` — recipients (owner only). */
export function listUserPlaylistShares(
  playlistId: string,
): Promise<UserPlaylistShareList> {
  return apiFetch<UserPlaylistShareList>(
    `/user-playlists/${encodeURIComponent(playlistId)}/shares`,
  );
}

/**
 * `POST /api/user-playlists/{playlist_id}/shares` — share with an account by
 * email (owner only). Unknown or invalid recipients answer 400/404.
 */
export function shareUserPlaylist(
  playlistId: string,
  email: string,
): Promise<MutationResult<UserPlaylistShare>> {
  return apiMutation<UserPlaylistShare>(
    `/user-playlists/${encodeURIComponent(playlistId)}/shares`,
    { method: "POST", body: JSON.stringify({ email }) },
  );
}

/**
 * `DELETE /api/user-playlists/{playlist_id}/shares/{user_id}` — revoke a
 * recipient's access (owner only).
 */
export function unshareUserPlaylist(
  playlistId: string,
  userId: string,
): Promise<MutationResult<void>> {
  return apiMutation<void>(
    `/user-playlists/${encodeURIComponent(playlistId)}/shares/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
}

/**
 * `POST /api/user-playlists` — create a curated playlist.
 *
 * Online-only: the row id is created by the server, so there is no safe
 * offline stand-in. Offline callers get a friendly `offline_unavailable`.
 */
export async function createUserPlaylist(
  input: UserPlaylistInput,
): Promise<UserPlaylist> {
  if (isOffline()) throw offlineUnavailable();
  try {
    return await apiFetch<UserPlaylist>("/user-playlists", {
      method: "POST",
      body: JSON.stringify(input),
    });
  } catch (error) {
    if (isNetworkError(error)) throw offlineUnavailable();
    throw error;
  }
}

/** `GET /api/user-playlists/{playlist_id}` — playlist plus ordered tracks. */
export function getUserPlaylist(
  playlistId: string,
): Promise<UserPlaylistDetail> {
  return apiFetch<UserPlaylistDetail>(
    `/user-playlists/${encodeURIComponent(playlistId)}`,
  ).then(resolveUserPlaylistDetail);
}

/** `PATCH /api/user-playlists/{playlist_id}` — rename or edit description. */
export function updateUserPlaylist(
  playlistId: string,
  input: Partial<UserPlaylistInput>,
): Promise<MutationResult<UserPlaylist>> {
  return apiMutation<UserPlaylist>(
    `/user-playlists/${encodeURIComponent(playlistId)}`,
    { method: "PATCH", body: JSON.stringify(input) },
  );
}

/** `DELETE /api/user-playlists/{playlist_id}` — remove a curated playlist. */
export function deleteUserPlaylist(
  playlistId: string,
): Promise<MutationResult<void>> {
  return apiMutation<void>(`/user-playlists/${encodeURIComponent(playlistId)}`, {
    method: "DELETE",
  });
}

/**
 * `POST /api/user-playlists/{playlist_id}/tracks` — append a track.
 *
 * Idempotent: adding a track that is already in the playlist returns the
 * unchanged detail instead of creating a duplicate.
 */
export async function addUserPlaylistTrack(
  playlistId: string,
  trackId: string,
): Promise<MutationResult<UserPlaylistDetail>> {
  const result = await apiMutation<UserPlaylistDetail>(
    `/user-playlists/${encodeURIComponent(playlistId)}/tracks`,
    { method: "POST", body: JSON.stringify({ track_id: trackId }) },
  );
  return result.queued
    ? result
    : { queued: false, data: resolveUserPlaylistDetail(result.data) };
}

/** `DELETE /api/user-playlists/{playlist_id}/tracks/{track_id}` */
export function removeUserPlaylistTrack(
  playlistId: string,
  trackId: string,
): Promise<MutationResult<void>> {
  return apiMutation<void>(
    `/user-playlists/${encodeURIComponent(playlistId)}/tracks/${encodeURIComponent(trackId)}`,
    { method: "DELETE" },
  );
}

/** `PUT /api/user-playlists/{playlist_id}/tracks/order` — persist order. */
export async function reorderUserPlaylistTracks(
  playlistId: string,
  trackIds: string[],
): Promise<MutationResult<UserPlaylistDetail>> {
  const result = await apiMutation<UserPlaylistDetail>(
    `/user-playlists/${encodeURIComponent(playlistId)}/tracks/order`,
    { method: "PUT", body: JSON.stringify({ track_ids: trackIds }) },
  );
  return result.queued
    ? result
    : { queued: false, data: resolveUserPlaylistDetail(result.data) };
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
 * authenticated fetch flow apply before the browser saves the file.
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
