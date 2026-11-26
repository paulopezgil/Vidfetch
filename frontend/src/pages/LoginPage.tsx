import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import Button from "../components/Button";
import Card from "../components/Card";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import IconButton from "../components/IconButton";
import Logo from "../components/Logo";
import SegmentedButton from "../components/SegmentedButton";
import Spinner from "../components/Spinner";
import TextField from "../components/TextField";

type Mode = "signin" | "signup";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 8;

export default function LoginPage() {
  const { token, profile, loading, error, login, register } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{
    email?: string;
    password?: string;
  }>({});

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

  if (token) {
    // A pending account still has a session; `RequireApproved` holds it on
    // `/pending` until an administrator approves it.
    return <Navigate to={profile && !profile.is_approved ? "/pending" : "/"} replace />;
  }

  function switchMode(next: Mode) {
    setMode(next);
    setFormError(null);
    setFieldErrors({});
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const trimmedEmail = email.trim();
    const nextFieldErrors: { email?: string; password?: string } = {};
    if (!trimmedEmail) {
      nextFieldErrors.email = "Introdueix el teu correu electrònic.";
    } else if (!EMAIL_PATTERN.test(trimmedEmail)) {
      nextFieldErrors.email = "El format del correu electrònic no és vàlid.";
    }
    if (!password) {
      nextFieldErrors.password = "Introdueix la teva contrasenya.";
    } else if (mode === "signup" && password.length < MIN_PASSWORD_LENGTH) {
      nextFieldErrors.password =
        `La contrasenya ha de tenir com a mínim ${MIN_PASSWORD_LENGTH} caràcters.`;
    }
    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) return;

    setSubmitting(true);
    try {
      if (mode === "signin") {
        await login(trimmedEmail, password);
      } else {
        await register(trimmedEmail, password);
      }
    } catch (e) {
      setFormError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut completar l’accés. Torna-ho a provar.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-surface px-4 py-10 text-on-surface">
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center text-center">
          <Logo className="h-16 w-16" />
          <h1 className="mt-4 text-headline-medium text-on-surface">Vidfetch</h1>
          <p className="mt-1 text-body-large text-on-surface-variant">
            El teu descarregador de vídeo i àudio
          </p>
        </div>

        <Card variant="elevated" className="space-y-5 p-6 sm:p-8">
          <div className="space-y-1 text-center">
            <h2 className="text-title-large text-on-surface">
              {mode === "signup" ? "Crea un compte" : "Inicia sessió"}
            </h2>
            <p className="text-body-medium text-on-surface-variant">
              Fes servir el teu correu electrònic i la teva contrasenya per
              continuar.
            </p>
          </div>

          {error ? <ErrorBanner message={error} /> : null}
          {formError ? <ErrorBanner message={formError} /> : null}

          <SegmentedButton
            label="Tipus d’accés"
            value={mode}
            onChange={(value) =>
              switchMode(value === "signup" ? "signup" : "signin")
            }
            options={[
              { value: "signin", label: "Inicia sessió", icon: "login" },
              { value: "signup", label: "Crea un compte", icon: "person_add" },
            ]}
          />

          <form
            className="space-y-4"
            onSubmit={(event) => void handleSubmit(event)}
            noValidate
          >
            <TextField
              id="login-email"
              label="Correu electrònic"
              type="email"
              inputMode="email"
              autoComplete="email"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={email}
              disabled={submitting}
              error={Boolean(fieldErrors.email)}
              helperText={fieldErrors.email}
              onChange={(event) => {
                setEmail(event.target.value);
                setFieldErrors((previous) => ({
                  ...previous,
                  email: undefined,
                }));
              }}
            />
            <TextField
              id="login-password"
              label="Contrasenya"
              type={showPassword ? "text" : "password"}
              autoComplete={
                mode === "signin" ? "current-password" : "new-password"
              }
              required
              value={password}
              disabled={submitting}
              error={Boolean(fieldErrors.password)}
              helperText={
                fieldErrors.password ??
                (mode === "signup"
                  ? `Mínim ${MIN_PASSWORD_LENGTH} caràcters.`
                  : undefined)
              }
              onChange={(event) => {
                setPassword(event.target.value);
                setFieldErrors((previous) => ({
                  ...previous,
                  password: undefined,
                }));
              }}
              endAdornment={
                <IconButton
                  label={
                    showPassword
                      ? "Amaga la contrasenya"
                      : "Mostra la contrasenya"
                  }
                  onClick={() => setShowPassword((visible) => !visible)}
                  disabled={submitting}
                >
                  <Icon
                    name={showPassword ? "visibility_off" : "visibility"}
                    className="text-[20px]"
                  />
                </IconButton>
              }
            />
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? (
                <Spinner />
              ) : (
                <Icon
                  name={mode === "signin" ? "login" : "person_add"}
                  className="text-[20px]"
                />
              )}
              {mode === "signin" ? "Inicia sessió" : "Crea el compte"}
            </Button>
          </form>

          <div className="flex items-start gap-3 rounded-md bg-surface-container-high p-3 text-on-surface-variant">
            <Icon name="info" className="shrink-0 text-[20px]" />
            <p className="text-body-small">
              Els comptes nous queden pendents fins que un administrador els
              aprova. Un cop aprovat, podràs descarregar contingut.
            </p>
          </div>

          <p className="text-center text-body-small text-on-surface-variant">
            En continuar, acceptes les condicions d’ús i la política de
            privadesa. Només fem servir el teu compte per identificar-te.
          </p>
        </Card>

        <p className="mt-6 text-center text-body-small text-on-surface-variant">
          Powered by yt-dlp
        </p>
      </div>
    </div>
  );
}
