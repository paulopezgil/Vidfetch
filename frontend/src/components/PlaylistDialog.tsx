import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { UserPlaylist } from "../types/v2";
import { createUserPlaylist, updateUserPlaylist } from "../lib/api";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import TextArea from "./TextArea";
import TextField from "./TextField";

interface PlaylistDialogProps {
  open: boolean;
  /** Playlist to edit, or `null`/omitted to create a new one. */
  playlist?: UserPlaylist | null;
  onClose: () => void;
  /** Called with the created or updated playlist after a successful save. */
  onSaved: (playlist: UserPlaylist) => void;
}

const NAME_MAX = 200;
const DESCRIPTION_MAX = 500;

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Material 3 dialog for creating or editing a curated playlist.
 *
 * Name is required and capped at 200 characters; the description is optional
 * and capped at 500. Validation errors stay inline and never discard input.
 */
export default function PlaylistDialog({
  open,
  playlist = null,
  onClose,
  onSaved,
}: PlaylistDialogProps) {
  const headingId = useId();
  const errorId = useId();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  // Reset the form each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setName(playlist?.name ?? "");
    setDescription(playlist?.description ?? "");
    setError(null);
    setBusy(false);
  }, [open, playlist]);

  // Escape closes (unless saving), Tab stays inside, focus starts on the name.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      dialogRef.current
        ?.querySelector<HTMLInputElement>('input[type="text"]')
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

  if (!open) return null;

  const editing = playlist !== null;
  const trimmedName = name.trim();
  const trimmedDescription = description.trim();

  function requestClose() {
    if (busy) return;
    onClose();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    if (!trimmedName) {
      setError("Cal un nom per a la llista.");
      return;
    }
    if (trimmedName.length > NAME_MAX) {
      setError(`El nom no pot superar els ${NAME_MAX} caràcters.`);
      return;
    }
    if (trimmedDescription.length > DESCRIPTION_MAX) {
      setError(
        `La descripció no pot superar els ${DESCRIPTION_MAX} caràcters.`,
      );
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const saved =
        playlist === null
          ? await createUserPlaylist({
              name: trimmedName,
              ...(trimmedDescription
                ? { description: trimmedDescription }
                : {}),
            })
          : await updateUserPlaylist(playlist.id, {
              name: trimmedName,
              description: trimmedDescription,
            });
      onSaved(saved);
      onClose();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut desar la llista de reproducció.",
      );
    } finally {
      setBusy(false);
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
        aria-busy={busy}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-[480px] rounded-t-xl bg-surface-container-high text-on-surface shadow-elevation-3 sm:rounded-xl"
      >
        <form onSubmit={(event) => void handleSubmit(event)}>
          <div className="flex items-start justify-between gap-2 px-6 pt-5">
            <div className="min-w-0">
              <h2 id={headingId} className="text-headline-small">
                {editing ? "Edit playlist" : "Create playlist"}
              </h2>
              <p className="mt-0.5 text-body-small text-on-surface-variant">
                {editing
                  ? "Update the name and description."
                  : "Give your playlist a name. You can add tracks afterwards."}
              </p>
            </div>
            <IconButton label="Tanca" onClick={requestClose} disabled={busy}>
              <Icon name="close" className="text-[20px]" />
            </IconButton>
          </div>

          <div className="space-y-4 px-6 pb-2 pt-5">
            <TextField
              id="playlist-name"
              label="Name"
              value={name}
              maxLength={NAME_MAX}
              disabled={busy}
              autoComplete="off"
              helperText={`${name.length}/${NAME_MAX}`}
              onChange={(event) => setName(event.target.value)}
            />

            <TextArea
              id="playlist-description"
              label="Description (optional)"
              value={description}
              maxLength={DESCRIPTION_MAX}
              disabled={busy}
              rows={3}
              helperText={`${description.length}/${DESCRIPTION_MAX}`}
              onChange={(event) => setDescription(event.target.value)}
            />

            {error ? (
              <p
                id={errorId}
                role="alert"
                className="rounded-sm bg-error-container px-3 py-2 text-body-small text-on-error-container"
              >
                {error}
              </p>
            ) : null}
          </div>

          <div className="flex justify-end gap-2 px-6 pb-6 pt-4">
            <Button
              type="button"
              variant="text"
              onClick={requestClose}
              disabled={busy}
            >
              Cancel·la
            </Button>
            <Button type="submit" variant="filled" disabled={busy}>
              {busy ? <Spinner className="text-[18px]" /> : null}
              {editing ? "Save" : "Create"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
