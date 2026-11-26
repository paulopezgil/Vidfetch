import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { UserPlaylist, UserPlaylistShare } from "../types/v2";
import {
  listUserPlaylistShares,
  shareUserPlaylist,
  unshareUserPlaylist,
} from "../lib/api";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import TextField from "./TextField";
import { useToast } from "./Toast";

interface SharePlaylistDialogProps {
  open: boolean;
  /** Playlist whose recipients are managed; must be owned by the caller. */
  playlist: UserPlaylist | null;
  onClose: () => void;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Material 3 dialog for sharing a curated playlist with other accounts.
 *
 * Loads the current recipients when it opens, lets the owner add one by email
 * and revoke any existing share. API failures (unknown account, invalid email,
 * not the owner) are shown inline in Catalan and never discard typed input.
 */
export default function SharePlaylistDialog({
  open,
  playlist,
  onClose,
}: SharePlaylistDialogProps) {
  const toast = useToast();
  const headingId = useId();
  const errorId = useId();
  const emailId = useId();
  const playlistId = playlist?.id ?? null;

  const [shares, setShares] = useState<UserPlaylistShare[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [adding, setAdding] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(false);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    busyRef.current = adding || removingId !== null;
  }, [adding, removingId]);

  // Load the current recipients each time the dialog opens.
  useEffect(() => {
    if (!open || !playlistId) return;
    let cancelled = false;
    setShares([]);
    setLoadError(null);
    setEmail("");
    setError(null);
    setAdding(false);
    setRemovingId(null);
    setLoading(true);

    listUserPlaylistShares(playlistId)
      .then((list) => {
        if (!cancelled) setShares(list.items);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLoadError(
          e instanceof Error
            ? e.message
            : "No s’ha pogut carregar la llista de destinataris.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, playlistId]);

  // Escape closes (unless a request is in flight) and Tab stays inside.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      dialogRef.current
        ?.querySelector<HTMLInputElement>('input:not([type="hidden"])')
        ?.focus();
    });

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busyRef.current) onCloseRef.current();
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
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      restoreRef.current?.focus?.();
    };
  }, [open]);

  if (!open || !playlist) return null;

  const busy = adding || removingId !== null;

  function requestClose() {
    if (busy) return;
    onClose();
  }

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!playlistId || busy) return;
    const trimmed = email.trim();
    if (!trimmed) {
      setError("Escriu el correu electrònic de la persona.");
      return;
    }
    if (!EMAIL_PATTERN.test(trimmed)) {
      setError("Escriu un correu electrònic vàlid.");
      return;
    }

    setAdding(true);
    setError(null);
    try {
      const result = await shareUserPlaylist(playlistId, trimmed);
      if (result.queued) {
        toast(result.message, "info");
        setEmail("");
        return;
      }
      const added = result.data;
      setShares((prev) =>
        prev.some((share) => share.user_id === added.user_id)
          ? prev
          : [...prev, added],
      );
      setEmail("");
      toast(`Llista compartida amb ${added.email}`, "success");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut compartir la llista amb aquest correu.",
      );
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(share: UserPlaylistShare) {
    if (!playlistId || busy) return;
    setRemovingId(share.user_id);
    setError(null);
    try {
      const result = await unshareUserPlaylist(playlistId, share.user_id);
      setShares((prev) =>
        prev.filter((item) => item.user_id !== share.user_id),
      );
      toast(
        result.queued ? result.message : `Accés retirat a ${share.email}`,
        result.queued ? "info" : "success",
      );
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut retirar l’accés d’aquesta persona.",
      );
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-scrim/32 p-0 sm:items-center sm:p-4"
      onClick={requestClose}
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        aria-describedby={error ? errorId : undefined}
        aria-busy={busy || loading}
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[92vh] w-full max-w-[520px] flex-col rounded-t-xl bg-surface-container-high text-on-surface shadow-elevation-3 sm:rounded-xl"
      >
        <div className="flex items-start justify-between gap-2 px-6 pt-5">
          <div className="min-w-0">
            <h2 id={headingId} className="text-headline-small">
              Comparteix la llista
            </h2>
            <p className="mt-0.5 truncate text-body-small text-on-surface-variant">
              {playlist.name}
            </p>
          </div>
          <IconButton label="Tanca" onClick={requestClose} disabled={busy}>
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>

        <div className="space-y-4 overflow-y-auto px-6 pb-2 pt-5">
          <p className="text-body-medium text-on-surface-variant">
            Les persones convidades poden escoltar i descarregar les cançons,
            però no poden editar la llista.
          </p>

          <form onSubmit={(event) => void handleAdd(event)} className="space-y-3">
            <TextField
              id={emailId}
              label="Correu electrònic"
              type="email"
              inputMode="email"
              autoComplete="off"
              value={email}
              disabled={busy}
              onChange={(event) => setEmail(event.target.value)}
            />
            <div className="flex justify-end">
              <Button type="submit" variant="tonal" disabled={busy}>
                {adding ? <Spinner className="text-[18px]" /> : null}
                <Icon name="person_add" className="text-[18px]" />
                Comparteix
              </Button>
            </div>
          </form>

          {error ? (
            <p
              id={errorId}
              role="alert"
              className="rounded-sm bg-error-container px-3 py-2 text-body-small text-on-error-container"
            >
              {error}
            </p>
          ) : null}

          <section aria-labelledby={`${headingId}-recipients`} className="space-y-2">
            <h3
              id={`${headingId}-recipients`}
              className="text-title-small text-on-surface"
            >
              Amb accés
            </h3>

            {loading ? (
              <p className="flex items-center gap-2 py-3 text-body-medium text-on-surface-variant">
                <Spinner /> S’estan carregant els destinataris…
              </p>
            ) : loadError ? (
              <p
                role="alert"
                className="rounded-sm bg-error-container px-3 py-2 text-body-small text-on-error-container"
              >
                {loadError}
              </p>
            ) : shares.length === 0 ? (
              <p className="py-2 text-body-medium text-on-surface-variant">
                Encara no has compartit aquesta llista amb ningú.
              </p>
            ) : (
              <ul className="divide-y divide-outline-variant overflow-hidden rounded-md border border-outline-variant">
                {shares.map((share) => (
                  <li
                    key={share.user_id}
                    className="flex items-center gap-3 bg-surface px-3 py-2"
                  >
                    <Icon
                      name="alternate_email"
                      className="shrink-0 text-[20px] text-on-surface-variant"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body-medium text-on-surface">
                        {share.email}
                      </span>
                      <span className="block text-label-small text-on-surface-variant">
                        Només lectura
                      </span>
                    </span>
                    <IconButton
                      variant="danger"
                      label={`Retira l’accés a ${share.email}`}
                      onClick={() => void handleRemove(share)}
                      disabled={busy}
                    >
                      {removingId === share.user_id ? (
                        <Spinner className="text-[20px]" />
                      ) : (
                        <Icon name="person_remove" className="text-[20px]" />
                      )}
                    </IconButton>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div className="flex justify-end gap-2 px-6 pb-6 pt-4">
          <Button variant="filled" onClick={requestClose} disabled={busy}>
            Fet
          </Button>
        </div>
      </div>
    </div>
  );
}
