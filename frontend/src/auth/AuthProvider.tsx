import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { AuthSession, Profile } from "../types/auth";
import {
  ApiError,
  getMe,
  isNetworkError,
  login as apiLogin,
  logout as apiLogout,
  register as apiRegister,
} from "../lib/api";
import {
  clearToken,
  getToken,
  setToken,
  subscribeUnauthorized,
} from "../lib/session";
import {
  cacheProfile,
  clearCachedProfile,
  readCachedProfile,
} from "../offline/profile";
import { clearCachedResponsesAndQueue } from "../offline/db";
import { isOffline, resetOfflineStatus } from "../offline/status";
import { flushQueue, resetQueueFlush } from "../offline/sync";
import { setActivePlaylistTitle } from "../navigation";

interface AuthContextValue {
  /** Bearer token for the current session. `null` when signed out. */
  token: string | null;
  /** Caller profile from `GET /api/me`; source of truth for approval/role. */
  profile: Profile | null;
  /** True while the initial session/profile bootstrap is running. */
  loading: boolean;
  /** User-facing error from the session or profile bootstrap. */
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  /**
   * Create an account. New accounts start unapproved, so the normal `/pending`
   * flow applies.
   */
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Human-readable copy for the stable API error codes. */
const authErrorMessages: Record<string, string> = {
  invalid_credentials: "El correu o la contrasenya no són correctes.",
  email_taken: "Ja existeix un compte amb aquest correu electrònic.",
  weak_password:
    "La contrasenya és massa feble. Fes servir com a mínim 8 caràcters.",
  invalid_email: "L’adreça de correu electrònic no és vàlida.",
  session_expired: "La sessió ha caducat. Torna a iniciar sessió.",
  approval_required: "El teu compte encara no està aprovat.",
  admin_required: "Aquesta acció requereix permisos d’administració.",
  invalid_request: "Revisa les dades introduïdes i torna-ho a provar.",
};

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return authErrorMessages[error.code] ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return "S'ha produït un error inesperat.";
}

/** True when the response says the session is gone for good. */
function isExpiredSession(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 401 || error.code === "session_expired")
  );
}

/**
 * Provider for the local bearer session plus the backend profile
 * (`GET /api/me`).
 *
 * The token lives in `lib/session`, never in React state alone, so a reload
 * keeps the session. The profile is fetched on boot and cached per browser for
 * offline boots; it is never used to authorize a request.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch `GET /api/me` for the stored token.
   *
   * With `offlineFallback`, a transport failure falls back to the cached
   * profile and keeps the token, so an offline reload still opens the shell.
   */
  const loadProfile = useCallback(
    async (options: { offlineFallback?: boolean } = {}) => {
      if (!getToken()) {
        setProfile(null);
        return;
      }

      try {
        const next = await getMe();
        setProfile(next);
        setError(null);
        // Keep a local copy so a reload without connectivity can still boot
        // the shell instead of bouncing to the login or error screen.
        cacheProfile(next);
        // The profile is only reachable with a valid session, so this is the
        // natural moment to replay edits queued while offline.
        void flushQueue();
      } catch (e) {
        if (isExpiredSession(e)) {
          // `authorizedFetch` already dropped the token and notified listeners.
          setProfile(null);
          setError(null);
          return;
        }
        if (options.offlineFallback && (isNetworkError(e) || isOffline())) {
          const cached = readCachedProfile();
          if (cached) {
            setProfile(cached);
            setError(null);
            return;
          }
        }
        setProfile(null);
        setError(describeError(e));
      }
    },
    [],
  );

  // Boot: read the stored token and load the profile behind it.
  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }

    let active = true;
    void (async () => {
      await loadProfile({ offlineFallback: true });
      if (active) setLoading(false);
    })();

    return () => {
      active = false;
    };
  }, [loadProfile]);

  // A rejected token (expired, revoked, password changed elsewhere) signs the
  // user out of this tab. Queued offline edits are kept: the same account can
  // sign back in and replay them.
  useEffect(
    () =>
      subscribeUnauthorized(() => {
        clearToken();
        setTokenState(null);
        setProfile(null);
        setError(null);
        setLoading(false);
        setActivePlaylistTitle(null);
      }),
    [],
  );

  const adoptSession = useCallback(async (session: AuthSession) => {
    const cached = readCachedProfile();
    if (cached && cached.id !== session.profile.id) {
      // Another account's leftovers: its cached pages and queued edits must not
      // leak into this account.
      await clearCachedResponsesAndQueue();
      resetOfflineStatus();
    }

    // Any replay still running belongs to the previous session.
    resetQueueFlush();

    setToken(session.token);
    setTokenState(session.token);
    setProfile(session.profile);
    cacheProfile(session.profile);
    setError(null);
    void flushQueue();
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      setError(null);
      try {
        const session = await apiLogin(email.trim(), password);
        await adoptSession(session);
      } catch (e) {
        throw new Error(describeError(e));
      }
    },
    [adoptSession],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      setError(null);
      try {
        const session = await apiRegister(email.trim(), password);
        await adoptSession(session);
      } catch (e) {
        throw new Error(describeError(e));
      }
    },
    [adoptSession],
  );

  const logout = useCallback(async () => {
    setError(null);
    // Stop any running replay first: its queued edits belong to this account
    // and must not be written back after the local queues are cleared.
    resetQueueFlush();

    try {
      // Best effort: an unreachable server must not block signing out locally.
      if (getToken()) await apiLogout();
    } catch {
      // Ignore transport and revocation errors here.
    } finally {
      // Multiple accounts share one browser: drop everything identity-scoped
      // so the next account never sees this library or replays its edits.
      // Offline media (saved songs) is global and stays untouched.
      clearToken();
      await clearCachedResponsesAndQueue();
      resetOfflineStatus();
      setActivePlaylistTitle(null);
      clearCachedProfile();
      setTokenState(null);
      setProfile(null);
    }
  }, []);

  const refreshProfile = useCallback(async () => {
    setError(null);
    // Keep the cached profile while offline so a pending user can retry later
    // without being bounced to the error screen.
    await loadProfile({ offlineFallback: true });
  }, [loadProfile]);

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      profile,
      loading,
      error,
      login,
      register,
      logout,
      refreshProfile,
    }),
    [token, profile, loading, error, login, register, logout, refreshProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return value;
}
