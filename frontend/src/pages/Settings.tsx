import { useState, type FormEvent } from "react";
import { changePassword } from "../lib/api";
import Button from "../components/Button";
import Card from "../components/Card";
import Icon from "../components/Icon";
import IconButton from "../components/IconButton";
import SegmentedButton from "../components/SegmentedButton";
import Spinner from "../components/Spinner";
import TextField from "../components/TextField";
import { useToast } from "../components/Toast";
import { useTheme, type ThemeMode } from "../theme/ThemeProvider";

const APPEARANCE_OPTIONS = [
  { value: "system", label: "Sistema", icon: "brightness_auto" },
  { value: "light", label: "Clar", icon: "light_mode" },
  { value: "dark", label: "Fosc", icon: "dark_mode" },
];

const MIN_PASSWORD_LENGTH = 8;
const MAX_PASSWORD_LENGTH = 200;

interface PasswordFieldErrors {
  current?: string;
  next?: string;
  confirm?: string;
}

/**
 * Appearance, language and account-security preferences.
 *
 * Appearance is fully wired to the theme provider. Language is a static
 * placeholder for now: Catalan is the only supported locale and the control is
 * disabled until the i18n layer exists. The security form replaces a password
 * that may have been reset by an administrator.
 */
export default function Settings() {
  const { mode, resolvedTheme, setMode } = useTheme();
  const toast = useToast();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<PasswordFieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  function clearFieldErrors(...keys: Array<keyof PasswordFieldErrors>) {
    setFieldErrors((previous) => {
      const next = { ...previous };
      for (const key of keys) next[key] = undefined;
      return next;
    });
    setFormError(null);
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setFormError(null);
    const errors: PasswordFieldErrors = {};

    if (!currentPassword) {
      errors.current = "Introdueix la contrasenya actual.";
    }
    if (!newPassword) {
      errors.next = "Introdueix una contrasenya nova.";
    } else if (newPassword.length < MIN_PASSWORD_LENGTH) {
      errors.next = `La contrasenya nova ha de tenir com a mínim ${MIN_PASSWORD_LENGTH} caràcters.`;
    } else if (newPassword.length > MAX_PASSWORD_LENGTH) {
      errors.next = `La contrasenya nova no pot superar els ${MAX_PASSWORD_LENGTH} caràcters.`;
    } else if (newPassword === currentPassword) {
      errors.next = "La contrasenya nova ha de ser diferent de l’actual.";
    }
    if (!confirmPassword) {
      errors.confirm = "Repeteix la contrasenya nova.";
    } else if (confirmPassword !== newPassword) {
      errors.confirm = "Les contrasenyes noves no coincideixen.";
    }

    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setShowCurrent(false);
      setShowNew(false);
      setFieldErrors({});
      setFormError(null);
      toast("Contrasenya actualitzada", "success");
    } catch (e) {
      setFormError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut canviar la contrasenya. Torna-ho a provar.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
      <div>
        <h2 className="text-title-large text-on-surface">Preferències</h2>
        <p className="mt-1 text-body-medium text-on-surface-variant">
          Ajusta l’aspecte, l’idioma i la seguretat del teu compte.
        </p>
      </div>

      <section aria-labelledby="settings-appearance" className="space-y-3">
        <h3
          id="settings-appearance"
          className="text-title-medium text-on-surface"
        >
          Aparença
        </h3>
        <Card variant="outlined" className="space-y-4 p-4 sm:p-5">
          <div>
            <p className="text-body-large text-on-surface">Mode de color</p>
            <p className="mt-0.5 text-body-small text-on-surface-variant">
              «Sistema» segueix la configuració del dispositiu; «Clar» i «Fosc»
              la sobreescriuen.
            </p>
          </div>

          <SegmentedButton
            label="Mode de color"
            value={mode}
            onChange={(value) => setMode(value as ThemeMode)}
            options={APPEARANCE_OPTIONS}
          />

          <p
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 text-body-small text-on-surface-variant"
          >
            <Icon
              name={resolvedTheme === "dark" ? "dark_mode" : "light_mode"}
              className="text-[18px]"
            />
            S’està mostrant el tema{" "}
            {resolvedTheme === "dark" ? "fosc" : "clar"}.
          </p>
        </Card>
      </section>

      <section aria-labelledby="settings-language" className="space-y-3">
        <h3
          id="settings-language"
          className="text-title-medium text-on-surface"
        >
          Idioma
        </h3>
        <Card variant="outlined" className="space-y-4 p-4 sm:p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-body-large text-on-surface">
                Llengua de la interfície
              </p>
              <p className="mt-0.5 text-body-small text-on-surface-variant">
                Només hi ha un idioma disponible.
              </p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-secondary-container px-3 py-1 text-label-medium text-on-secondary-container">
              <Icon name="check" className="text-[16px]" />
              Seleccionat
            </span>
          </div>

          <div
            aria-disabled="true"
            className="flex h-12 items-center justify-between gap-3 rounded-sm border border-outline-variant px-4 opacity-[0.38]"
          >
            <span className="truncate text-body-large text-on-surface">
              Català
            </span>
            <Icon name="check" className="shrink-0 text-[20px] text-on-surface" />
          </div>

          <div className="flex items-start gap-3 rounded-md bg-surface-container-high p-3 text-on-surface-variant">
            <Icon name="translate" className="shrink-0 text-[20px]" />
            <p className="text-body-small">Més idiomes aviat.</p>
          </div>
        </Card>
      </section>

      <section aria-labelledby="settings-security" className="space-y-3">
        <h3
          id="settings-security"
          className="text-title-medium text-on-surface"
        >
          Seguretat
        </h3>
        <Card variant="outlined" className="space-y-4 p-4 sm:p-5">
          <p className="text-body-medium text-on-surface-variant">
            Canvia la contrasenya del teu compte. Si un administrador t’ha
            restablert la contrasenya, substitueix aquí la temporal.
          </p>

          <form
            className="space-y-4"
            onSubmit={(event) => void handlePasswordSubmit(event)}
            noValidate
            aria-busy={submitting}
          >
            <TextField
              id="settings-current-password"
              name="current-password"
              label="Contrasenya actual"
              type={showCurrent ? "text" : "password"}
              autoComplete="current-password"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={currentPassword}
              disabled={submitting}
              error={Boolean(fieldErrors.current)}
              helperText={fieldErrors.current}
              onChange={(event) => {
                setCurrentPassword(event.target.value);
                clearFieldErrors("current", "next");
              }}
              endAdornment={
                <IconButton
                  label={
                    showCurrent
                      ? "Amaga la contrasenya actual"
                      : "Mostra la contrasenya actual"
                  }
                  onClick={() => setShowCurrent((visible) => !visible)}
                  disabled={submitting}
                >
                  <Icon
                    name={showCurrent ? "visibility_off" : "visibility"}
                    className="text-[20px]"
                  />
                </IconButton>
              }
            />

            <TextField
              id="settings-new-password"
              name="new-password"
              label="Contrasenya nova"
              type={showNew ? "text" : "password"}
              autoComplete="new-password"
              autoCapitalize="none"
              spellCheck={false}
              required
              minLength={MIN_PASSWORD_LENGTH}
              maxLength={MAX_PASSWORD_LENGTH}
              value={newPassword}
              disabled={submitting}
              error={Boolean(fieldErrors.next)}
              helperText={
                fieldErrors.next ??
                `Entre ${MIN_PASSWORD_LENGTH} i ${MAX_PASSWORD_LENGTH} caràcters.`
              }
              onChange={(event) => {
                setNewPassword(event.target.value);
                clearFieldErrors("next", "confirm");
              }}
              endAdornment={
                <IconButton
                  label={
                    showNew
                      ? "Amaga la contrasenya nova"
                      : "Mostra la contrasenya nova"
                  }
                  onClick={() => setShowNew((visible) => !visible)}
                  disabled={submitting}
                >
                  <Icon
                    name={showNew ? "visibility_off" : "visibility"}
                    className="text-[20px]"
                  />
                </IconButton>
              }
            />

            <TextField
              id="settings-confirm-password"
              name="confirm-password"
              label="Repeteix la contrasenya nova"
              type="password"
              autoComplete="new-password"
              autoCapitalize="none"
              spellCheck={false}
              required
              minLength={MIN_PASSWORD_LENGTH}
              maxLength={MAX_PASSWORD_LENGTH}
              value={confirmPassword}
              disabled={submitting}
              error={Boolean(fieldErrors.confirm)}
              helperText={fieldErrors.confirm}
              onChange={(event) => {
                setConfirmPassword(event.target.value);
                clearFieldErrors("confirm");
              }}
            />

            {formError ? (
              <p
                role="alert"
                className="rounded-sm bg-error-container px-3 py-2 text-body-small text-on-error-container"
              >
                {formError}
              </p>
            ) : null}

            <div className="flex justify-end">
              <Button type="submit" disabled={submitting}>
                {submitting ? (
                  <Spinner className="text-[18px]" />
                ) : (
                  <Icon name="lock_reset" className="text-[18px]" />
                )}
                {submitting ? "Canviant…" : "Canvia la contrasenya"}
              </Button>
            </div>
          </form>
        </Card>
      </section>
    </div>
  );
}
