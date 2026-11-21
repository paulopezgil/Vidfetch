import { useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import Button from "../components/Button";
import Card from "../components/Card";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import Spinner from "../components/Spinner";

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-surface px-4 py-10 text-on-surface">
      <div className="w-full max-w-md">{children}</div>
    </div>
  );
}

function LoadingScreen({ label = "Carregant el teu compte…" }: { label?: string }) {
  return (
    <div
      className="flex min-h-full flex-col items-center justify-center gap-3 bg-surface px-4 py-10 text-on-surface-variant"
      role="status"
      aria-live="polite"
    >
      <Spinner className="text-[32px]" />
      <p className="text-body-medium">{label}</p>
    </div>
  );
}

function AuthErrorScreen() {
  const { error, refreshProfile, signOut } = useAuth();
  const [retrying, setRetrying] = useState(false);

  async function retry() {
    setRetrying(true);
    try {
      await refreshProfile();
    } finally {
      setRetrying(false);
    }
  }

  return (
    <Centered>
      <Card variant="filled" className="space-y-4 p-6">
        <div className="flex items-center gap-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-error-container text-on-error-container">
            <Icon name="error" className="text-[24px]" />
          </span>
          <h1 className="text-title-large text-on-surface">
            No s’ha pogut carregar el teu perfil
          </h1>
        </div>
        <ErrorBanner
          message={error ?? "El servei no ha respost correctament."}
        />
        <p className="text-body-medium text-on-surface-variant">
          Comprova la connexió i torna-ho a provar. Si el problema continua, tanca
          la sessió i torna a entrar.
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="text" onClick={() => void signOut()}>
            Tanca la sessió
          </Button>
          <Button onClick={() => void retry()} disabled={retrying}>
            {retrying ? <Spinner /> : <Icon name="refresh" className="text-[20px]" />}
            Torna-ho a provar
          </Button>
        </div>
      </Card>
    </Centered>
  );
}

/** UX guard: anonymous visitors are sent to the login page. */
export function RequireAuth() {
  const { session, profile, loading, error } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingScreen />;
  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (!profile && error) return <AuthErrorScreen />;
  if (!profile) return <LoadingScreen label="Carregant el perfil…" />;
  return <Outlet />;
}

/** UX guard: authenticated but unapproved accounts go to `/pending`. */
export function RequireApproved() {
  const { session, profile, loading, error } = useAuth();

  if (loading) return <LoadingScreen />;
  if (!session) return <Navigate to="/login" replace />;
  if (!profile && error) return <AuthErrorScreen />;
  if (!profile) return <LoadingScreen label="Carregant el perfil…" />;
  if (!profile.is_approved) return <Navigate to="/pending" replace />;
  return <Outlet />;
}

function NotAuthorized() {
  const navigate = useNavigate();

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-10">
      <Card variant="filled" className="w-full max-w-md p-6 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-error-container text-on-error-container">
          <Icon name="lock" className="text-[32px]" />
        </div>
        <h1 className="mt-4 text-headline-small text-on-surface">
          Accés no autoritzat
        </h1>
        <p className="mt-2 text-body-medium text-on-surface-variant">
          Aquesta secció només està disponible per a administradors. Si creus que
          és un error, posa’t en contacte amb l’administrador de l’aplicació.
        </p>
        <div className="mt-6 flex justify-center">
          <Button onClick={() => navigate("/")}>
            <Icon name="home" className="text-[20px]" />
            Torna a l’inici
          </Button>
        </div>
      </Card>
    </div>
  );
}

/** UX guard: renders a not-authorized state for non-admin users. */
export function RequireAdmin() {
  const { session, profile, loading, error } = useAuth();

  if (loading) return <LoadingScreen />;
  if (!session) return <Navigate to="/login" replace />;
  if (!profile && error) return <AuthErrorScreen />;
  if (!profile) return <LoadingScreen label="Carregant el perfil…" />;
  if (profile.app_role !== "admin") return <NotAuthorized />;
  return <Outlet />;
}
