import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { supabaseConfigError } from "../lib/supabase";
import Button from "../components/Button";
import Card from "../components/Card";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import Spinner from "../components/Spinner";

export default function LoginPage() {
  const { session, profile, loading, error, signInWithGoogle } = useAuth();
  const [signingIn, setSigningIn] = useState(false);

  if (loading) {
    return (
      <div
        className="flex min-h-full flex-col items-center justify-center gap-3 bg-surface px-4 text-on-surface-variant"
        role="status"
        aria-live="polite"
      >
        <Spinner className="text-[32px]" />
        <p className="text-body-medium">Carregant…</p>
      </div>
    );
  }

  if (session) {
    return <Navigate to={profile?.is_approved ? "/" : "/pending"} replace />;
  }

  const message = supabaseConfigError ?? error;

  async function handleSignIn() {
    setSigningIn(true);
    try {
      await signInWithGoogle();
    } finally {
      setSigningIn(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-surface px-4 py-10 text-on-surface">
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center text-center">
          <img src="/favicon.svg" alt="" className="h-16 w-16" />
          <h1 className="mt-4 text-headline-medium text-on-surface">Vidfetch</h1>
          <p className="mt-1 text-body-large text-on-surface-variant">
            El teu descarregador de vídeo i àudio
          </p>
        </div>

        <Card variant="elevated" className="space-y-5 p-6 sm:p-8">
          <div className="space-y-1 text-center">
            <h2 className="text-title-large text-on-surface">Inicia sessió</h2>
            <p className="text-body-medium text-on-surface-variant">
              Fes servir el teu compte de Google per continuar.
            </p>
          </div>

          {message ? <ErrorBanner message={message} /> : null}

          <Button
            variant="outlined"
            className="w-full"
            onClick={() => void handleSignIn()}
            disabled={signingIn || Boolean(supabaseConfigError)}
          >
            {signingIn ? (
              <Spinner />
            ) : (
              <img src="/google-g.svg" alt="" className="h-5 w-5" />
            )}
            Continua amb Google
          </Button>

          <div className="flex items-start gap-3 rounded-md bg-surface-container-high p-3 text-on-surface-variant">
            <Icon name="info" className="text-[20px] shrink-0" />
            <p className="text-body-small">
              Els comptes nous queden pendents fins que un administrador els
              aprova. Un cop aprovat, podràs descarregar contingut.
            </p>
          </div>

          <p className="text-center text-body-small text-on-surface-variant">
            En continuar, acceptes les condicions d’ús i la política de
            privadesa. Només fem servir el teu compte de Google per
            identificar-te; no publiquem res en nom teu.
          </p>
        </Card>

        <p className="mt-6 text-center text-body-small text-on-surface-variant">
          Powered by yt-dlp
        </p>
      </div>
    </div>
  );
}
