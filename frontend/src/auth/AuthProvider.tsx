import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Session } from "@supabase/supabase-js";
import type { Profile } from "../types/auth";
import { getMe } from "../lib/api";
import { supabase, supabaseConfigError } from "../lib/supabase";

interface AuthContextValue {
  /** Supabase session. `null` when signed out. */
  session: Session | null;
  /** Caller profile from `GET /api/me`; source of truth for approval/role. */
  profile: Profile | null;
  /** True while the initial session/profile bootstrap is running. */
  loading: boolean;
  /** User-facing error from the session or profile bootstrap. */
  error: string | null;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "S'ha produït un error inesperat.";
}

/** Provider for Supabase Auth plus the backend profile (`GET /api/me`). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(supabaseConfigError);

  const loadProfile = useCallback(async () => {
    if (!supabase) {
      setError(supabaseConfigError);
      setProfile(null);
      return;
    }
    try {
      const next = await getMe();
      setProfile(next);
      setError(null);
    } catch (e) {
      setProfile(null);
      setError(describeError(e));
    }
  }, []);

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }

    let active = true;
    let initialized = false;
    const client = supabase;

    async function sync(next: Session | null) {
      if (!active) return;
      setSession(next);
      if (!next) {
        setProfile(null);
        setError(null);
        setLoading(false);
        return;
      }
      await loadProfile();
      if (active) setLoading(false);
    }

    client.auth
      .getSession()
      .then(({ data, error: sessionError }) => {
        if (!active) return;
        initialized = true;
        if (sessionError) {
          setError(sessionError.message);
          setLoading(false);
          return;
        }
        void sync(data.session);
      })
      .catch((e: unknown) => {
        if (!active) return;
        setError(describeError(e));
        setLoading(false);
      });

    const { data: listener } = client.auth.onAuthStateChange(
      (event, next) => {
        if (!active || !initialized) return;
        // The initial session is already handled by getSession().
        if (event === "INITIAL_SESSION") return;
        if (event === "TOKEN_REFRESHED") {
          setSession(next);
          return;
        }
        // Supabase warns against calling auth methods inside this callback, so
        // defer the profile fetch to the next task.
        window.setTimeout(() => {
          void sync(next);
        }, 0);
      },
    );

    return () => {
      active = false;
      listener.subscription.unsubscribe();
    };
  }, [loadProfile]);

  const signInWithGoogle = useCallback(async () => {
    if (!supabase) {
      setError(supabaseConfigError);
      return;
    }
    setError(null);
    try {
      const { error: signInError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: window.location.origin },
      });
      if (signInError) setError(signInError.message);
    } catch (e) {
      setError(describeError(e));
    }
  }, []);

  const signOut = useCallback(async () => {
    if (!supabase) return;
    setError(null);
    try {
      const { error: signOutError } = await supabase.auth.signOut();
      if (signOutError) setError(signOutError.message);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setSession(null);
      setProfile(null);
    }
  }, []);

  const refreshProfile = useCallback(async () => {
    if (!supabase) {
      setError(supabaseConfigError);
      return;
    }
    setError(null);
    await loadProfile();
  }, [loadProfile]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      profile,
      loading,
      error,
      signInWithGoogle,
      signOut,
      refreshProfile,
    }),
    [
      session,
      profile,
      loading,
      error,
      signInWithGoogle,
      signOut,
      refreshProfile,
    ],
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
