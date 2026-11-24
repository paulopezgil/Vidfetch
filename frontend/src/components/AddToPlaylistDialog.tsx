import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
} from "react";
import type { Track, UserPlaylist } from "../types/v2";
import {
  addUserPlaylistTrack,
  createUserPlaylist,
  listUserPlaylists,
} from "../lib/api";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import TextField from "./TextField";
import { useToast } from "./Toast";

interface AddToPlaylistDialogProps {
  open: boolean;
  /** Track being added, or `null` when the dialog is closed. */
  track: Track | null;
  onClose: () => void;
}

const NAME_MAX = 200;
const LIST_LIMIT = 100;

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Material 3 dialog listing the caller's curated playlists so the current
 * track can be appended to one.
 *
 * The API is idempotent, so re-adding a track reports that it was already
 * there instead of surfacing an error. A quick inline form can create a new
 * playlist and add the track in one step without stacking modals.
 */
export default function AddToPlaylistDialog({
  open,
  track,
  onClose,
}: AddToPlaylistDialogProps) {
  const toast = useToast();
  const headingId = useId();
  const errorId = useId();

  const [playlists, setPlaylists] = useState<UserPlaylist[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(false);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    busyRef.current = busyId !== null || formBusy;
  }, [busyId, formBusy]);

  const trackId = track?.id ?? null;

  // Reload the playlist list each time the dialog opens for a track.
  useEffect(() => {
    if (!open || !trackId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setBusyId(null);
    setFormOpen(false);
    setNewName("");
    setFormError(null);

    void listUserPlaylists({ limit: LIST_LIMIT })
      .then((page) => {
        if (!cancelled) setPlaylists(page.items);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "No s’han pogut carregar les llistes.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open, trackId, reloadToken]);

  // Escape closes (unless busy) and Tab stays inside the dialog.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      dialogRef.current?.focus();
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

  if (!open || !track) return null;

  const busy = busyId !== null || formBusy;

  function requestClose() {
    if (busy) return;
    onClose();
  }

  async function handleAdd(playlist: UserPlaylist) {
    if (!track || busy) return;
    setBusyId(playlist.id);
    setError(null);
    try {
      const detail = await addUserPlaylistTrack(playlist.id, track.id);
      // An unchanged count means the idempotent endpoint found the track
      // already in this playlist.
      const alreadyThere = detail.track_count <= playlist.track_count;
      toast(
        alreadyThere
          ? `«${track.title}» ja era a «${playlist.name}»`
          : `«${track.title}» afegit a «${playlist.name}»`,
        alreadyThere ? "info" : "success",
      );
      onClose();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No s’ha pogut afegir el track.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function handleCreateAndAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!track || busy) return;

    const name = newName.trim();
    if (!name) {
      setFormError("Cal un nom per a la llista.");
      return;
    }
    if (name.length > NAME_MAX) {
      setFormError(`El nom no pot superar els ${NAME_MAX} caràcters.`);
      return;
    }

    setFormBusy(true);
    setFormError(null);
    try {
      const playlist = await createUserPlaylist({ name });
      // Show the new playlist immediately; if appending the track fails the
      // dialog stays open and the user can retry without creating a duplicate.
      setPlaylists((prev) => [playlist, ...prev]);
      setFormOpen(false);
      setNewName("");
      try {
        await addUserPlaylistTrack(playlist.id, track.id);
        toast(`«${track.title}» afegit a «${playlist.name}»`, "success");
        onClose();
      } catch (e) {
        setError(
          e instanceof Error
            ? `La llista s’ha creat, però no s’ha pogut afegir el track: ${e.message}`
            : "La llista s’ha creat, però no s’ha pogut afegir el track.",
        );
      }
    } catch (e) {
      setFormError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut crear la llista de reproducció.",
      );
    } finally {
      setFormBusy(false);
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
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[92vh] w-full max-w-[480px] flex-col rounded-t-xl bg-surface-container-high text-on-surface shadow-elevation-3 focus:outline-none sm:rounded-xl"
      >
        <div className="flex items-start justify-between gap-2 px-6 pt-5">
          <div className="min-w-0">
            <h2 id={headingId} className="text-headline-small">
              Afegeix a una playlist
            </h2>
            <p className="mt-0.5 truncate text-body-small text-on-surface-variant">
              {track.title || "Track sense títol"}
            </p>
          </div>
          <IconButton label="Tanca" onClick={requestClose} disabled={busy}>
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 pt-4">
          {loading ? (
            <div className="flex items-center justify-center gap-3 py-10 text-body-medium text-on-surface-variant">
              <Spinner /> S’estan carregant les llistes…
            </div>
          ) : playlists.length > 0 ? (
            <ul aria-label="Les meves llistes de reproducció">
              {playlists.map((playlist) => (
                <li key={playlist.id}>
                  <button
                    type="button"
                    onClick={() => void handleAdd(playlist)}
                    disabled={busy}
                    className="flex w-full items-center gap-3 rounded-md px-4 py-3 text-left transition-colors hover:bg-on-surface/8 focus-visible:bg-on-surface/12 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-[0.38]"
                  >
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-secondary-container text-on-secondary-container">
                      <Icon name="queue_music" className="text-[20px]" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body-large text-on-surface">
                        {playlist.name}
                      </span>
                      <span className="block text-label-medium text-on-surface-variant">
                        {playlist.track_count}{" "}
                        {playlist.track_count === 1 ? "track" : "tracks"}
                      </span>
                    </span>
                    {busyId === playlist.id ? (
                      <Spinner />
                    ) : (
                      <Icon
                        name="add"
                        className="text-[20px] text-on-surface-variant"
                      />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-4 py-6 text-center text-body-medium text-on-surface-variant">
              Encara no tens cap llista de reproducció. Crea’n una aquí sota.
            </p>
          )}

          {error ? (
            <div className="mx-4 mt-3 rounded-sm bg-error-container px-3 py-2 text-on-error-container">
              <p id={errorId} role="alert" className="text-body-small">
                {error}
              </p>
              {!loading && playlists.length === 0 ? (
                <button
                  type="button"
                  onClick={() => setReloadToken((value) => value + 1)}
                  className="mt-1 inline-flex items-center gap-1.5 rounded-sm px-2 py-1 text-label-large transition-colors hover:bg-on-error-container/8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-on-error-container"
                >
                  <Icon name="refresh" className="text-[18px]" />
                  Torna-ho a provar
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="border-t border-outline-variant p-4 sm:px-6">
          {formOpen ? (
            <form
              onSubmit={(event) => void handleCreateAndAdd(event)}
              className="space-y-3"
            >
              <TextField
                id="new-playlist-name"
                label="Nom de la llista"
                value={newName}
                maxLength={NAME_MAX}
                disabled={busy}
                autoComplete="off"
                helperText={`${newName.length}/${NAME_MAX}`}
                onChange={(event) => setNewName(event.target.value)}
              />
              {formError ? (
                <p
                  role="alert"
                  className="rounded-sm bg-error-container px-3 py-2 text-body-small text-on-error-container"
                >
                  {formError}
                </p>
              ) : null}
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="text"
                  onClick={() => {
                    setFormOpen(false);
                    setFormError(null);
                  }}
                  disabled={busy}
                >
                  Cancel·la
                </Button>
                <Button type="submit" variant="filled" disabled={busy}>
                  {formBusy ? <Spinner className="text-[18px]" /> : null}
                  Crea i afegeix
                </Button>
              </div>
            </form>
          ) : (
            <Button
              variant="outlined"
              className="w-full"
              onClick={() => setFormOpen(true)}
              disabled={busy}
            >
              <Icon name="add" className="text-[18px]" />
              New playlist
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
