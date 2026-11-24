import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import type { FacetItem, FacetList, Track } from "../types/v2";
import {
  COVER_CONTENT_TYPES,
  MAX_COVER_BYTES,
  deleteTrackCover,
  listAlbumFacets,
  listArtistFacets,
  updateTrack,
  uploadTrackCover,
} from "../lib/api";
import { useMediaToken } from "../lib/useMediaToken";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import TextField from "./TextField";
import Thumbnail from "./Thumbnail";

interface TrackEditDialogProps {
  open: boolean;
  track: Track | null;
  onClose: () => void;
  /** Called with the saved track so the page can refresh its row. */
  onSaved: (track: Track) => void;
}

const FIELD_MAX = 200;
const SUGGESTION_DELAY_MS = 250;

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface FacetHandle {
  items: FacetItem[];
  /** Fetch immediately with the current query (used on focus). */
  refresh: () => void;
}

/**
 * Debounced facet suggestions for a text field.
 *
 * Fetches once when the dialog opens, again ~250 ms after typing pauses, and
 * immediately on focus. A stale response never overwrites a newer one.
 */
function useFacetSuggestions(
  load: (q: string) => Promise<FacetList>,
  query: string,
  enabled: boolean,
): FacetHandle {
  const [items, setItems] = useState<FacetItem[]>([]);
  const requestRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const queryRef = useRef(query);
  queryRef.current = query;

  const run = useCallback(
    (term: string) => {
      const request = ++requestRef.current;
      void load(term)
        .then((list) => {
          if (request === requestRef.current) setItems(list.items);
        })
        .catch(() => {
          // Suggestions are an enhancement; typing itself must keep working.
        });
    },
    [load],
  );

  useEffect(() => {
    if (!enabled) {
      setItems([]);
      return;
    }
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      run(query.trim());
    }, SUGGESTION_DELAY_MS);
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, query, run]);

  const refresh = useCallback(() => {
    run(queryRef.current.trim());
  }, [run]);

  return { items, refresh };
}

function coverTypeLabel(type: string): string {
  return type.replace("image/", "").toUpperCase();
}

/** Material 3 dialog for editing a track's metadata and cover art. */
export default function TrackEditDialog({
  open,
  track,
  onClose,
  onSaved,
}: TrackEditDialogProps) {
  const headingId = useId();
  const artistListId = useId();
  const albumListId = useId();
  const coverHintId = useId();
  const errorId = useId();

  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [album, setAlbum] = useState("");
  const [coverFile, setCoverFile] = useState<File | null>(null);
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [removeCover, setRemoveCover] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dialogRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  const artistSuggestions = useFacetSuggestions(listArtistFacets, artist, open);
  const albumSuggestions = useFacetSuggestions(listAlbumFacets, album, open);
  const { token } = useMediaToken(open ? (track?.asset_id ?? null) : null);

  // Reset the form each time the dialog opens for a track.
  useEffect(() => {
    if (!open || !track) return;
    setTitle(track.title ?? "");
    setArtist(track.artist ?? "");
    setAlbum(track.album ?? "");
    setCoverFile(null);
    setRemoveCover(false);
    setBusy(false);
    setError(null);
  }, [open, track]);

  // Local object URL for the picked file, revoked when it is replaced/closed.
  useEffect(() => {
    if (!coverFile) {
      setCoverPreview(null);
      return;
    }
    const url = URL.createObjectURL(coverFile);
    setCoverPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [coverFile]);

  // Escape closes (unless saving) and Tab stays inside the dialog.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    // Focus the first text field, not the hidden file input or a button.
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

  if (!open || !track) return null;

  const hasStoredCover = Boolean(track.cover_path || track.cover_url);
  const showStoredCover = hasStoredCover && !removeCover;
  const coverSrc =
    coverPreview ??
    (showStoredCover ? (track.cover_url ?? token?.thumbnail_url ?? null) : null);
  const hasCoverControls = coverFile !== null || hasStoredCover;

  function requestClose() {
    if (busy) return;
    onClose();
  }

  function handlePickFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    // Clearing the value lets the user pick the same file again after an error.
    event.target.value = "";
    if (!file) return;
    if (!(COVER_CONTENT_TYPES as readonly string[]).includes(file.type)) {
      setError(
        `Format no admès (${coverTypeLabel(file.type) || "desconegut"}). Fes servir JPEG, PNG o WebP.`,
      );
      return;
    }
    if (file.size > MAX_COVER_BYTES) {
      setError("La imatge supera el límit de 5 MiB.");
      return;
    }
    setError(null);
    setCoverFile(file);
    setRemoveCover(false);
  }

  function handleCoverAction() {
    if (coverFile) {
      setCoverFile(null);
      return;
    }
    if (removeCover) {
      setRemoveCover(false);
      return;
    }
    setRemoveCover(true);
  }

  async function handleSave() {
    if (!track || busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await updateTrack(track.id, {
        custom_title: title.trim(),
        custom_artist: artist.trim(),
        custom_album: album.trim(),
      });

      let coverUrl = updated.cover_url;
      if (coverFile) {
        const cover = await uploadTrackCover(track.id, coverFile);
        coverUrl = cover.cover_url;
      } else if (removeCover && hasStoredCover) {
        await deleteTrackCover(track.id);
        coverUrl = null;
      }

      setBusy(false);
      onSaved({ ...updated, cover_url: coverUrl });
      onClose();
    } catch (e) {
      setBusy(false);
      setError(
        e instanceof Error
          ? e.message
          : "No s’han pogut desar els canvis del track.",
      );
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
        className="flex max-h-[92vh] w-full max-w-[560px] flex-col rounded-t-xl bg-surface-container-high text-on-surface shadow-elevation-3 sm:rounded-xl"
      >
        <div className="flex items-start justify-between gap-2 px-6 pt-5">
          <div className="min-w-0">
            <h2 id={headingId} className="text-headline-small">
              Edita els detalls
            </h2>
            <p className="mt-0.5 truncate text-body-small text-on-surface-variant">
              {track.title || "Track sense títol"}
            </p>
          </div>
          <IconButton label="Tanca" onClick={requestClose} disabled={busy}>
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>

        <div className="space-y-4 overflow-y-auto px-6 pb-2 pt-4">
          <div className="flex items-start gap-4">
            <Thumbnail
              src={coverSrc}
              icon="music_note"
              className="h-24 w-24 rounded-lg"
            />
            <div className="min-w-0 space-y-1.5">
              <p className="text-label-large text-on-surface">Portada</p>
              <p id={coverHintId} className="text-body-small text-on-surface-variant">
                JPEG, PNG o WebP · màxim 5 MiB
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outlined"
                  size="sm"
                  disabled={busy}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Icon name="add_photo_alternate" className="text-[18px]" />
                  Tria una imatge
                </Button>
                {hasCoverControls ? (
                  <Button
                    variant="text"
                    size="sm"
                    disabled={busy}
                    onClick={handleCoverAction}
                  >
                    <Icon name="delete" className="text-[18px]" />
                    {coverFile
                      ? "Descarta la imatge"
                      : removeCover
                        ? "Recupera la portada"
                        : "Treu la portada"}
                  </Button>
                ) : null}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept={COVER_CONTENT_TYPES.join(",")}
                tabIndex={-1}
                aria-label="Tria una imatge de portada"
                aria-describedby={coverHintId}
                className="hidden"
                onChange={handlePickFile}
              />
            </div>
          </div>

          <TextField
            id="track-title"
            label="Títol"
            value={title}
            maxLength={FIELD_MAX}
            disabled={busy}
            onChange={(event) => setTitle(event.target.value)}
          />

          <TextField
            id="track-artist"
            label="Artista"
            value={artist}
            maxLength={FIELD_MAX}
            disabled={busy}
            list={artistListId}
            onFocus={artistSuggestions.refresh}
            onChange={(event) => setArtist(event.target.value)}
          />
          <datalist id={artistListId}>
            {artistSuggestions.items.map((item) => (
              <option key={item.name} value={item.name}>
                {item.track_count}
              </option>
            ))}
          </datalist>

          <TextField
            id="track-album"
            label="Àlbum"
            value={album}
            maxLength={FIELD_MAX}
            disabled={busy}
            list={albumListId}
            onFocus={albumSuggestions.refresh}
            onChange={(event) => setAlbum(event.target.value)}
          />
          <datalist id={albumListId}>
            {albumSuggestions.items.map((item) => (
              <option key={item.name} value={item.name}>
                {item.track_count}
              </option>
            ))}
          </datalist>

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
          <Button variant="text" onClick={requestClose} disabled={busy}>
            Cancel·la
          </Button>
          <Button
            variant="filled"
            onClick={() => void handleSave()}
            disabled={busy}
          >
            {busy ? <Spinner className="text-[18px]" /> : null}
            Desa
          </Button>
        </div>
      </div>
    </div>
  );
}
