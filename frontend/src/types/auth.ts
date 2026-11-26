/** Application role stored in `profiles.app_role` (never a token claim). */
export type AppRole = "user" | "admin";

/** Current caller as returned by `GET /api/me`. */
export interface Profile {
  id: string;
  email: string;
  is_approved: boolean;
  app_role: AppRole;
  approved_at?: string | null;
  approved_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

/**
 * Successful `POST /api/auth/login` and `POST /api/auth/register` response.
 *
 * `token` is an opaque bearer token; `profile` is a convenience copy of the
 * caller profile and is never auth proof on its own.
 */
export interface AuthSession {
  token: string;
  expires_at: string;
  profile: Profile;
}

/** Row shape returned by the admin user-management endpoints. */
export interface AdminUser extends Profile {}

/** Paginated response for `GET /api/admin/users`. */
export interface AdminUserList {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

/** Consistent error envelope used by the v2 API. */
export interface ApiErrorShape {
  error: {
    code: string;
    message: string;
  };
}
