import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import Button from "../components/Button";
import Card from "../components/Card";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import Logo from "../components/Logo";
import Spinner from "../components/Spinner";

export default function PendingPage() {
  const { profile, loading, error, refreshProfile, logout } = useAuth();
  const [refreshing, setRefreshing] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  if (profile?.is_approved) {
    return <Navigate to="/" replace />;
  }

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshProfile();
    } finally {
      setRefreshing(false);
    }
  }

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-surface px-4 py-10 text-on-surface">
      <div className="w-full max-w-lg">
        <div className="mb-6 flex flex-col items-center text-center">
          <Logo className="h-14 w-14" />
          <h1 className="mt-3 text-title-large text-on-surface">Vidfetch</h1>
        </div>

        <Card variant="elevated" className="space-y-5 p-6 sm:p-8">
          <div className="flex flex-col items-center text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-warning-container text-on-warning-container">
              <Icon name="hourglass_top" className="text-[32px]" />
            </div>
            <h2 className="mt-4 text-headline-small text-on-surface">
              Compte pendent d’aprovació
            </h2>
            <p className="mt-2 text-body-medium text-on-surface-variant">
              El teu compte s’ha creat correctament, però encara no té accés a
              les descàrregues. Un administrador l’ha d’aprovar manualment.
            </p>
            {profile?.email ? (
              <p className="mt-3 rounded-sm bg-surface-container-high px-3 py-1 text-body-medium text-on-surface">
                {profile.email}
              </p>
            ) : null}
          </div>

          {error ? <ErrorBanner message={error} /> : null}

          <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
            <Button
              onClick={() => void handleRefresh()}
              disabled={refreshing || loading}
            >
              {refreshing || loading ? (
                <Spinner />
              ) : (
                <Icon name="refresh" className="text-[20px]" />
              )}
              Actualitza l’estat
            </Button>
            <Button
              variant="text"
              onClick={() => void handleSignOut()}
              disabled={signingOut}
            >
              {signingOut ? (
                <Spinner />
              ) : (
                <Icon name="logout" className="text-[20px]" />
              )}
              Tanca la sessió
            </Button>
          </div>

          <p className="text-center text-body-small text-on-surface-variant">
            Si fa temps que esperes, posa’t en contacte amb l’administrador de
            l’aplicació i indica el correu anterior.
          </p>
        </Card>
      </div>
    </div>
  );
}
