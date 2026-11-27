import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { AdminUser } from "../types/auth";
import { resetUserPassword } from "../lib/api";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import TextField from "./TextField";

interface AdminPasswordResetDialogProps {
  open: boolean;
  /** Account whose password is being reset. */
  user: AdminUser | null;
  onClose: () => void;
  /** Called after a successful reset, while the one-time view stays open. */
  onReset: (user: AdminUser) => void;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const MIN_PASSWORD_LENGTH = 8;
const MAX_PASSWORD_LENGTH = 200;
const GENERATED_PASSWORD_LENGTH = 20;

const LOWER = "abcdefghijkmnopqrstuvwxyz";
const UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ";
const DIGITS = "23456789";
const SYMBOLS = "!@#$%^&*()-_=+[]{}?";
const ALL_CHARS = `${LOWER}${UPPER}${DIGITS}${SYMBOLS}`;

/** Uniform random integer below `max`, using rejection sampling. */
function randomInt(max: number): number {
  const buffer = new Uint32Array(1);
  const limit = Math.floor(0x1_0000_0000 / max) * max;
  let value = 0;
  do {
    crypto.getRandomValues(buffer);
    value = buffer[0] ?? 0;
  } while (value >= limit);
  return value % max;
}

function randomChar(chars: string): string {
  return chars.charAt(randomInt(chars.length));
}

function shuffle(value: string[]): void {
  for (let index = value.length - 1; index > 0; index -= 1) {
    const swap = randomInt(index + 1);
    const current = value[index];
    value[index] = value[swap];
    value[swap] = current;
  }
}

/** Strong 20-character password with at least one of each character class. */
function generatePassword(): string | null {
  if (
    typeof crypto === "undefined" ||
    typeof crypto.getRandomValues !== "function"
  ) {
    return null;
  }

  const chars = [
    randomChar(LOWER),
    randomChar(UPPER),
    randomChar(DIGITS),
    randomChar(SYMBOLS),
  ];
  while (chars.length < GENERATED_PASSWORD_LENGTH) {
    chars.push(randomChar(ALL_CHARS));
  }
  shuffle(chars);
  return chars.join("");
}

function fallbackCopy(value: string): void {
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  let copied = false;
  try {
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    textarea.remove();
  }
  if (!copied) throw new Error("copy_failed");
}

/**
 * Admin-only password reset dialog.
 *
 * The entered temporary password is sent to the server and never logged. After
 * a successful reset the dialog switches to a one-time view; closing it clears
 * the password and the result from component state.
 */
export default function AdminPasswordResetDialog({
  open,
  user,
  onClose,
  onReset,
}: AdminPasswordResetDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const fieldId = useId();

  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(false);

  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    busyRef.current = submitting;
  }, [submitting]);

  const clearSensitive = useCallback(() => {
    setPassword("");
    setShowPassword(false);
    setSubmitting(false);
    setError(null);
    setFieldError(null);
    setResult(null);
    setCopied(false);
    setCopyError(null);
  }, []);

  // A fresh open (or a different target) starts with an empty form. Closing
  // clears every trace of the temporary credential.
  useEffect(() => {
    clearSensitive();
  }, [clearSensitive, open, user?.id]);

  // Escape closes unless the reset request is in flight; Tab stays inside.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busyRef.current) {
          clearSensitive();
          onCloseRef.current();
        }
        return;
      }
      if (event.key !== "Tab") return;
      const focusable =
        dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      restoreRef.current?.focus?.();
    };
  }, [clearSensitive, open]);

  // Focus the password field, then the copy action once the result appears.
  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      if (result) {
        dialogRef.current
          ?.querySelector<HTMLButtonElement>(
            'button[aria-label="Copia la contrasenya"]',
          )
          ?.focus();
      } else {
        dialogRef.current?.querySelector<HTMLInputElement>("input")?.focus();
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, result]);

  if (!open || !user) return null;

  function requestClose() {
    if (submitting) return;
    clearSensitive();
    onCloseRef.current();
  }

  function handleGenerate() {
    let generated: string | null = null;
    try {
      generated = generatePassword();
    } catch {
      generated = null;
    }
    if (!generated) {
      setError(
        "Aquest navegador no permet generar una contrasenya segura. Escriu-ne una manualment.",
      );
      return;
    }
    setPassword(generated);
    setShowPassword(true);
    setError(null);
    setFieldError(null);
    setCopied(false);
    setCopyError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user || submitting) return;

    setError(null);
    if (password.length < MIN_PASSWORD_LENGTH) {
      setFieldError(
        `La contrasenya ha de tenir com a mínim ${MIN_PASSWORD_LENGTH} caràcters.`,
      );
      return;
    }
    if (password.length > MAX_PASSWORD_LENGTH) {
      setFieldError(
        `La contrasenya no pot superar els ${MAX_PASSWORD_LENGTH} caràcters.`,
      );
      return;
    }
    setFieldError(null);
    setSubmitting(true);
    try {
      await resetUserPassword(user.id, password);
      setResult(password);
      setShowPassword(false);
      setError(null);
      onReset(user);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut restablir la contrasenya.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopy() {
    if (!result) return;
    setCopyError(null);
    try {
      if (
        navigator.clipboard &&
        typeof navigator.clipboard.writeText === "function"
      ) {
        await navigator.clipboard.writeText(result);
      } else {
        fallbackCopy(result);
      }
      setCopied(true);
    } catch {
      try {
        fallbackCopy(result);
        setCopied(true);
      } catch {
        setCopied(false);
        setCopyError(
          "No s’ha pogut copiar automàticament. Selecciona la contrasenya i copia-la manualment.",
        );
      }
    }
  }

  const description = result
    ? `La contrasenya temporal de ${user.email} només es mostra una vegada.`
    : `Restableixes la contrasenya de ${user.email}. Totes les seves sessions s’hauran de tancar.`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-scrim/32 p-0 sm:items-center sm:p-4"
      role="presentation"
      onClick={requestClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        aria-busy={submitting}
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[92vh] w-full max-w-[520px] flex-col rounded-t-xl bg-surface-container-high text-on-surface shadow-elevation-3 sm:rounded-xl"
      >
        <div className="flex items-start gap-2 px-6 pt-5">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-headline-small">
              {result ? "Contrasenya restablerta" : "Restableix la contrasenya"}
            </h2>
            <p
              id={descriptionId}
              className="mt-0.5 text-body-small text-on-surface-variant"
            >
              {description}
            </p>
          </div>
          <IconButton
            label="Tanca"
            onClick={requestClose}
            disabled={submitting}
          >
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>

        {result ? (
          <>
            <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-2 pt-5">
              <p className="text-label-large text-on-surface-variant">
                Contrasenya temporal
              </p>
              <code className="mt-2 block select-all break-all rounded-md border border-outline-variant bg-surface-container-lowest p-3 text-body-large text-on-surface">
                {result}
              </code>

              {copyError ? (
                <p
                  role="alert"
                  className="mt-3 rounded-sm bg-error-container px-3 py-2 text-body-small text-on-error-container"
                >
                  {copyError}
                </p>
              ) : null}

              <div className="mt-4 flex items-center gap-2">
                <Button
                  variant="tonal"
                  size="sm"
                  aria-label="Copia la contrasenya"
                  onClick={() => void handleCopy()}
                >
                  <Icon
                    name={copied ? "check" : "content_copy"}
                    className="text-[18px]"
                  />
                  {copied ? "Copiat" : "Copia"}
                </Button>
              </div>

              <div className="mt-4 flex items-start gap-3 rounded-md bg-warning-container p-3 text-on-warning-container">
                <Icon name="warning" className="shrink-0 text-[20px]" />
                <p className="text-body-small">
                  No es tornarà a mostrar. Desa-la ara en un lloc segur.
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 px-6 pb-6 pt-4">
              <Button variant="filled" onClick={requestClose}>
                Fet
              </Button>
            </div>
          </>
        ) : (
          <form
            onSubmit={(event) => void handleSubmit(event)}
            noValidate
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-2 pt-4">
              <div className="flex items-start gap-3 rounded-md bg-warning-container p-3 text-on-warning-container">
                <Icon name="warning" className="shrink-0 text-[20px]" />
                <p className="text-body-small">
                  En restablir-la, es tancaran{" "}
                  <strong>totes les sessions</strong> d’aquest compte. La
                  contrasenya només es mostrarà una vegada.
                </p>
              </div>

              <TextField
                id={fieldId}
                label="Contrasenya temporal"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                autoCapitalize="none"
                spellCheck={false}
                required
                minLength={MIN_PASSWORD_LENGTH}
                maxLength={MAX_PASSWORD_LENGTH}
                value={password}
                disabled={submitting}
                error={Boolean(fieldError)}
                helperText={
                  fieldError ??
                  `Entre ${MIN_PASSWORD_LENGTH} i ${MAX_PASSWORD_LENGTH} caràcters. La contrasenya generada en té ${GENERATED_PASSWORD_LENGTH}.`
                }
                onChange={(event) => {
                  setPassword(event.target.value);
                  setFieldError(null);
                  setError(null);
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

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outlined"
                  size="sm"
                  onClick={handleGenerate}
                  disabled={submitting}
                >
                  <Icon name="autorenew" className="text-[18px]" />
                  Genera
                </Button>
                <span className="text-body-small text-on-surface-variant">
                  Crea una contrasenya temporal forta.
                </span>
              </div>

              {error ? (
                <p
                  role="alert"
                  className="rounded-sm bg-error-container px-3 py-2 text-body-small text-on-error-container"
                >
                  {error}
                </p>
              ) : null}
            </div>

            <div className="flex flex-wrap justify-end gap-2 px-6 pb-6 pt-4">
              <Button
                type="button"
                variant="text"
                onClick={requestClose}
                disabled={submitting}
              >
                Cancel·la
              </Button>
              <Button type="submit" disabled={submitting || !password}>
                {submitting ? (
                  <Spinner className="text-[18px]" />
                ) : (
                  <Icon name="key" className="text-[18px]" />
                )}
                {submitting ? "Restablint…" : "Restableix la contrasenya"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
