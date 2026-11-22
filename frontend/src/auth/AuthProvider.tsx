import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { AuthError, Session } from "@supabase/supabase-js";
import type { Profile } from "../types/auth";
import { getMe } from "../lib/api";
import { isLocalAuthEnabled } from "../lib/env";
import { supabase, supabaseConfigError } from "../lib/supabase";

/** Outcome of a development-only email/password sign-up. */
export interface PasswordSignUpResult {
  /**
   * True when Supabase requires the user to confirm their email address
   * before a session exists (the default for hosted projects).
   */
  needsEmailConfirmation: boolean;
}

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
  /**
   * Development-only email/password sign-in. Rejects when
   * `VITE_ENABLE_LOCAL_AUTH` is not `"true"`.
   */
  signInWithPassword: (email: string, password: string) => Promise<void>;
  /**
   * Development-only account creation. New accounts still start unapproved,
   * so the normal `/pending` flow applies.
   */
  signUpWithPassword: (
    email: string,
    password: string,
  ) => Promise<PasswordSignUpResult>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "S'ha produït un error inesperat.";
}

/**
 * Translate the Supabase Auth error codes that can realistically appear in
 * the local email/password form. Unknown codes keep the server message.
 */
const passwordAuthMessages: Record<string, string> = {
  invalid_credentials: "El correu o la contrasenya no són correctes.",
  email_not_confirmed:
    "Cal confirmar el correu electrònic abans d’iniciar sessió. Revisa la safata d’entrada.",
  user_already_exists: "Ja existeix un compte amb aquest correu.",
  email_exists: "Ja existeix un compte amb aquest correu.",
  weak_password: "La contrasenya és massa feble. Fes servir com a mínim 6 caràcters.",
  signup_disabled: "El registre amb correu està desactivat en aquest projecte.",
  email_address_invalid: "L’adreça de correu no és vàlida.",
  email_address_not_authorized:
    "Aquest domini de correu no està autoritzat per registrar-se.",
  validation_failed: "Revisa les dades introduïdes i torna-ho a provar.",
  over_email_send_rate_limit:
    "S’han enviat massa correus. Espera uns minuts i torna-ho a provar.",
  over_request_rate_limit:
    "Massa intents seguits. Espera uns minuts i torna-ho a provar.",
};

function passwordAuthError(error: AuthError): Error {
  return new Error(passwordAuthMessages[error.code ?? ""] ?? error.message);
}

/**
 * Both password methods are compile-time gated by the Vite env flag, so a
 * production bundle can never reach them even if the UI were tampered with.
 */
function requireLocalAuthClient() {
  if (!isLocalAuthEnabled) {
    throw new Error(
      "L’autenticació amb correu només està disponible en desenvolupament local.",
    );
  }
  if (!supabase) {
    throw new Error(supabaseConfigError ?? "Supabase no està configurat.");
  }
  return supabase;
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

  const signInWithPassword = useCallback(
    async (email: string, password: string) => {
      const client = requireLocalAuthClient();
      const { error: signInError } = await client.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (signInError) throw passwordAuthError(signInError);
      // The session and profile arrive through `onAuthStateChange`.
    },
    [],
  );

  const signUpWithPassword = useCallback(
    async (
      email: string,
      password: string,
    ): Promise<PasswordSignUpResult> => {
      const client = requireLocalAuthClient();
      const { data, error: signUpError } = await client.auth.signUp({
        email: email.trim(),
        password,
        options: { emailRedirectTo: window.location.origin },
      });
      if (signUpError) throw passwordAuthError(signUpError);
      return { needsEmailConfirmation: !data.session };
    },
    [],
  );

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
      signInWithPassword,
      signUpWithPassword,
      signOut,
      refreshProfile,
    }),
    [
      session,
      profile,
      loading,
      error,
      signInWithGoogle,
      signInWithPassword,
      signUpWithPassword,
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
