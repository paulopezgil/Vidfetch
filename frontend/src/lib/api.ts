import type {
  AdminUser,
  AdminUserList,
  ApiErrorShape,
  AppRole,
  Profile,
} from "../types/auth";
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
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
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
 * Authenticated JSON fetch.
 *
 * The current Supabase access token is attached automatically. A `401`
 * triggers exactly one session refresh and one retry; if the retry still fails
 * the parsed API error is thrown.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
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

  if (!res.ok) throw await parseError(res);
  return readBody<T>(res);
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
