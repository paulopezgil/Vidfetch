import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { Track, TrackUpdate } from "../types/v2";
import { updateTrack } from "../lib/api";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import TextField from "./TextField";

/** Which metadata field the group dialog edits. */
export type GroupEditKind = "artist" | "album";

interface GroupEditDialogProps {
  open: boolean;
  kind: GroupEditKind;
  /** Current group name; the fallback bucket passes an empty string. */
  name: string;
  /** Every track in the group; the edit is applied to all of them. */
  tracks: Track[];
  onClose: () => void;
  /**
   * Called after an apply attempt, with the number of tracks that could not be
   * saved. The page refreshes and regroups from the server response.
   */
  onApplied: (failed: number) => void;
}

const FIELD_MAX = 200;

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Material 3 dialog that renames an artist or album group in one go.
 *
 * Album groups can also fix the artist: the album is written to every track,
 * and the artist is only written when the field has a value. Every request is
 * independent, so a partial failure reports how many rows could not be saved
 * while keeping the dialog — and the remaining edits — usable.
 */
export default function GroupEditDialog({
  open,
  kind,
  name,
  tracks,
  onClose,
  onApplied,
}: GroupEditDialogProps) {
  const headingId = useId();
  const errorId = useId();

  const [album, setAlbum] = useState("");
  const [artist, setArtist] = useState("");
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

  const editingAlbum = kind === "album";

  // Reset the form each time the dialog opens for a group.
  useEffect(() => {
    if (!open) return;
    setAlbum(editingAlbum ? name : (tracks[0]?.album ?? ""));
    setArtist(editingAlbum ? (tracks[0]?.artist ?? "") : name);
    setBusy(false);
    setError(null);
    // `tracks` is intentionally read once per open/group change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editingAlbum, name]);

  // Escape closes (unless saving), Tab stays inside, focus starts on field 1.
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

  const trimmedAlbum = album.trim();
  const trimmedArtist = artist.trim();
  const requiredValue = editingAlbum ? trimmedAlbum : trimmedArtist;

  function requestClose() {
    if (busy) return;
    onClose();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    if (!requiredValue) {
      setError(
        editingAlbum
          ? "Cal un nom per a l’àlbum."
          : "Cal un nom per a l’artista.",
      );
      return;
    }
    if (requiredValue.length > FIELD_MAX) {
      setError(`El nom no pot superar els ${FIELD_MAX} caràcters.`);
      return;
    }
    if (editingAlbum && trimmedArtist.length > FIELD_MAX) {
      setError(`El nom no pot superar els ${FIELD_MAX} caràcters.`);
      return;
    }

    const payload: TrackUpdate = editingAlbum
      ? {
          custom_album: trimmedAlbum,
          // The artist is optional: clearing the field keeps whatever each
          // track already has.
          ...(trimmedArtist ? { custom_artist: trimmedArtist } : {}),
        }
      : { custom_artist: trimmedArtist };

    setBusy(true);
    setError(null);
    try {
      const results = await Promise.allSettled(
        tracks.map((track) => updateTrack(track.id, payload)),
      );
      const failed = results.filter(
        (result) => result.status === "rejected",
      ).length;
      if (failed > 0) {
        // Allow a retry without discarding the typed values.
        setError(
          `No s’han pogut desar ${failed} de ${tracks.length} tracks. Torna-ho a provar.`,
        );
        onApplied(failed);
        return;
      }
      onApplied(0);
      onClose();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’han pogut desar els canvis del grup.",
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
                {editingAlbum ? "Edita l’àlbum" : "Edita el grup"}
              </h2>
              <p className="mt-0.5 text-body-small text-on-surface-variant">
                {editingAlbum
                  ? `S’aplicarà a ${tracks.length} ${tracks.length === 1 ? "track" : "tracks"}. L’artista és opcional.`
                  : `S’aplicarà a ${tracks.length} ${tracks.length === 1 ? "track" : "tracks"}.`}
              </p>
            </div>
            <IconButton label="Tanca" onClick={requestClose} disabled={busy}>
              <Icon name="close" className="text-[20px]" />
            </IconButton>
          </div>

          <div className="space-y-4 px-6 pb-2 pt-5">
            {editingAlbum ? (
              <TextField
                id="group-album"
                label="Àlbum"
                value={album}
                maxLength={FIELD_MAX}
                disabled={busy}
                autoComplete="off"
                helperText={`${album.length}/${FIELD_MAX}`}
                onChange={(event) => setAlbum(event.target.value)}
              />
            ) : null}

            <TextField
              id="group-artist"
              label={editingAlbum ? "Artista (opcional)" : "Artista"}
              value={artist}
              maxLength={FIELD_MAX}
              disabled={busy}
              autoComplete="off"
              helperText={`${artist.length}/${FIELD_MAX}`}
              onChange={(event) => setArtist(event.target.value)}
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
              Aplica
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
