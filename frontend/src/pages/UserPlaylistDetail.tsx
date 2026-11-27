import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type {
  Track,
  UserPlaylist,
  UserPlaylistDetail as UserPlaylistDetailData,
} from "../types/v2";
import { formatDuration } from "../lib";
import {
  deleteUserPlaylist,
  getMediaToken,
  getUserPlaylist,
  removeUserPlaylistTrack,
  reorderUserPlaylistTracks,
  triggerDownload,
  withDownloadFlag,
} from "../lib/api";
import Button from "../components/Button";
import Card from "../components/Card";
import ConfirmDialog from "../components/ConfirmDialog";
import EmptyState from "../components/EmptyState";
import Icon from "../components/Icon";
import IconButton from "../components/IconButton";
import Menu from "../components/Menu";
import NowPlayingIndicator from "../components/NowPlayingIndicator";
import OfflineButton from "../components/OfflineButton";
import PlaylistCollage from "../components/PlaylistCollage";
import PlaylistDialog from "../components/PlaylistDialog";
import SharePlaylistDialog from "../components/SharePlaylistDialog";
import Spinner from "../components/Spinner";
import Thumbnail from "../components/Thumbnail";
import TrackEditDialog from "../components/TrackEditDialog";
import { useToast } from "../components/Toast";
import { useMediaToken } from "../lib/useMediaToken";
import { mediaTypeFor } from "../lib/trackDisplay";
import { usePlayer } from "../player/PlayerProvider";
import { setActivePlaylistTitle } from "../navigation";
import { QUEUED_MUTATION_MESSAGE, isOffline } from "../offline/status";

function trackIcon(track: Track): string {
  const mediaType = mediaTypeFor(track);
  if (mediaType === "audio") return "music_note";
  if (mediaType === "image") return "image";
  return "movie";
}

function trackCredit(track: Track): string {
  return [track.artist, track.album]
    .map((value) => value.trim())
    .filter((value) => value.length > 0)
    .join(" · ");
}

/** An older cached payload may not carry an `items` array at all. */
function normalizeDetail(
  detail: UserPlaylistDetailData,
): UserPlaylistDetailData {
  return {
    ...detail,
    items: Array.isArray(detail.items) ? detail.items : [],
  };
}

/** Curated playlist detail with ordering, playback and membership actions. */
export default function UserPlaylistDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { playTrack, updateTrack } = usePlayer();

  const [detail, setDetail] = useState<UserPlaylistDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editingTrack, setEditingTrack] = useState<Track | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [reordering, setReordering] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const next = await getUserPlaylist(id);
      setDetail(normalizeDetail(next));
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut carregar la llista de reproducció.",
      );
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    setDetail(null);
    void refresh();
  }, [refresh]);

  // Publish the playlist name for the top app bar title.
  useEffect(() => {
    setActivePlaylistTitle(null);
  }, [id]);
  useEffect(() => {
    setActivePlaylistTitle(detail?.name ?? null);
  }, [detail]);
  useEffect(() => () => setActivePlaylistTitle(null), []);

  const handleSaved = useCallback(
    (playlist: UserPlaylist, options?: { queued?: boolean }) => {
      setDetail((prev) =>
        prev && prev.id === playlist.id ? { ...prev, ...playlist } : prev,
      );
      toast(
        options?.queued
          ? QUEUED_MUTATION_MESSAGE
          : "Llista de reproducció actualitzada",
        options?.queued ? "info" : "success",
      );
    },
    [toast],
  );

  const handleTrackSaved = useCallback(
    (updated: Track) => {
      // Swap the row in place; ordering and membership stay as they are.
      setDetail((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : prev,
      );
      updateTrack(updated);
      toast("Cançó actualitzada", "success");
    },
    [toast, updateTrack],
  );

  const confirmDelete = useCallback(async () => {
    if (!detail || deleting) return;
    setDeleting(true);
    try {
      // Only the curated playlist rows are removed; tracks stay in the library.
      const result = await deleteUserPlaylist(detail.id);
      toast(
        result.queued ? result.message : "Llista de reproducció eliminada",
        result.queued ? "info" : "success",
      );
      setDeleteOpen(false);
      navigate("/playlists");
    } catch (e) {
      toast(
        e instanceof Error
          ? e.message
          : "No s’ha pogut eliminar la llista de reproducció",
        "error",
      );
    } finally {
      setDeleting(false);
    }
  }, [deleting, detail, navigate, toast]);

  const removeTrack = useCallback(
    async (track: Track) => {
      if (!detail || removingId || reordering) return;
      setRemovingId(track.id);
      try {
        const result = await removeUserPlaylistTrack(detail.id, track.id);
        setDetail((prev) =>
          prev
            ? {
                ...prev,
                items: prev.items.filter((item) => item.id !== track.id),
                track_count: Math.max(0, prev.track_count - 1),
              }
            : prev,
        );
        toast(
          result.queued ? result.message : "Cançó treta de la llista",
          result.queued ? "info" : "success",
        );
      } catch (e) {
        toast(
          e instanceof Error
            ? e.message
            : "No s’ha pogut treure la cançó de la llista",
          "error",
        );
      } finally {
        setRemovingId(null);
      }
    },
    [detail, removingId, reordering, toast],
  );

  const move = useCallback(
    async (index: number, delta: number) => {
      if (!detail || reordering || removingId) return;
      const target = index + delta;
      if (target < 0 || target >= detail.items.length) return;

      const nextItems = [...detail.items];
      const [moved] = nextItems.splice(index, 1);
      if (!moved) return;
      nextItems.splice(target, 0, moved);

      // Reorder optimistically, then persist the full id list. A queued result
      // keeps the local order; a failure reloads the server order instead of
      // leaving the UI out of sync.
      const previous = detail;
      setDetail({ ...detail, items: nextItems });
      setReordering(true);
      try {
        const result = await reorderUserPlaylistTracks(
          detail.id,
          nextItems.map((item) => item.id),
        );
        if (result.queued) {
          toast(result.message, "info");
        } else {
          setDetail(normalizeDetail(result.data));
        }
      } catch (e) {
        setDetail(previous);
        toast(
          e instanceof Error
            ? e.message
            : "No s’ha pogut desar l’ordre de la llista",
          "error",
        );
      } finally {
        setReordering(false);
      }
    },
    [detail, reordering, removingId, toast],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
        <Spinner /> S’està carregant la llista de reproducció…
      </div>
    );
  }

  if (error || !detail) {
    const offline = Boolean(error) && isOffline();
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6 lg:px-8">
        <Link
          to="/playlists"
          className="mb-4 inline-flex items-center gap-1.5 text-label-large text-primary hover:text-primary/80"
        >
          <Icon name="arrow_back" className="text-[20px]" /> Llistes
        </Link>
        <EmptyState
          icon={offline ? "cloud_off" : "playlist_remove"}
          title={
            offline
              ? "Aquesta llista no està disponible sense connexió"
              : "No s’ha trobat la llista de reproducció"
          }
          description={
            offline
              ? "Obre aquesta llista una vegada amb connexió perquè les seves dades es desin al dispositiu."
              : error ?? "Aquesta llista de reproducció no existeix."
          }
          action={
            <Button
              variant="outlined"
              onClick={() => {
                setLoading(true);
                void refresh();
              }}
            >
              <Icon name="refresh" className="text-[18px]" />
              Torna-ho a provar
            </Button>
          }
        />
      </div>
    );
  }

  const items = Array.isArray(detail.items) ? detail.items : [];
  // Older payloads have no flag; treat those playlists as the caller's own.
  const isOwner = detail.is_owner ?? true;
  const ownerLabel = detail.owner_email || "un altre usuari";

  function playAll() {
    if (items.length === 0) return;
    playTrack(items[0], items);
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <Link
        to="/playlists"
        className="inline-flex w-fit items-center gap-1.5 rounded-full pr-3 text-label-large text-primary hover:text-primary/80"
      >
        <Icon name="arrow_back" className="text-[20px]" /> Llistes
      </Link>

      <Card variant="outlined" className="p-4 sm:p-6">
        <div className="flex flex-col gap-5 sm:flex-row">
          <PlaylistCollage
            tracks={items}
            className="aspect-square w-full sm:w-48"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <h1 className="break-words text-headline-small text-on-surface">
                  {detail.name}
                </h1>
                <p className="mt-1 text-body-medium text-on-surface-variant">
                  {items.length} {items.length === 1 ? "cançó" : "cançons"}
                </p>
                {!isOwner ? (
                  <p className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full bg-secondary-container px-3 py-1 text-label-medium text-on-secondary-container">
                    <Icon name="share" className="shrink-0 text-[16px]" />
                    <span className="truncate">
                      Compartida per {ownerLabel}
                    </span>
                  </p>
                ) : null}
                {detail.description ? (
                  <p className="mt-1 max-w-prose whitespace-pre-line text-body-medium text-on-surface-variant">
                    {detail.description}
                  </p>
                ) : null}
              </div>
              {isOwner ? (
                <Menu
                  label="Opcions de la llista"
                  actions={[
                    {
                      id: "share",
                      label: "Comparteix",
                      icon: "share",
                      onSelect: () => setShareOpen(true),
                    },
                    {
                      id: "edit",
                      label: "Edita els detalls",
                      icon: "edit",
                      onSelect: () => setEditOpen(true),
                    },
                    {
                      id: "delete",
                      label: "Elimina la llista",
                      icon: "delete",
                      onSelect: () => setDeleteOpen(true),
                    },
                  ]}
                />
              ) : null}
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-2">
              <Button onClick={playAll} disabled={items.length === 0}>
                <Icon name="play_arrow" className="text-[18px]" />
                Reprodueix
              </Button>
              {isOwner ? (
                <Button
                  variant="outlined"
                  onClick={() => navigate(`/playlists/${detail.id}/add`)}
                >
                  <Icon name="playlist_add" className="text-[18px]" />
                  Afegeix cançons
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      </Card>

      {items.length > 0 ? (
        <Card variant="outlined" className="overflow-hidden">
          <ul className="divide-y divide-outline-variant">
            {items.map((track, index) => (
              <PlaylistTrackRow
                key={track.id}
                track={track}
                index={index}
                total={items.length}
                queue={items}
                reordering={reordering}
                removing={removingId === track.id}
                readOnly={!isOwner}
                onMoveUp={() => void move(index, -1)}
                onMoveDown={() => void move(index, 1)}
                onRemove={() => void removeTrack(track)}
                onEdit={() => setEditingTrack(track)}
              />
            ))}
          </ul>
        </Card>
      ) : (
        <EmptyState
          icon="queue_music"
          title="Aquesta llista és buida"
          description={
            isOwner
              ? "Afegeix cançons de la vostra biblioteca per començar a escoltar-les en ordre."
              : "El propietari encara no hi ha afegit cap cançó."
          }
          action={
            isOwner ? (
              <Button
                variant="outlined"
                onClick={() => navigate(`/playlists/${detail.id}/add`)}
              >
                <Icon name="playlist_add" className="text-[18px]" />
                Afegeix cançons
              </Button>
            ) : undefined
          }
        />
      )}

      {isOwner ? (
        <PlaylistDialog
          open={editOpen}
          playlist={detail}
          onClose={() => setEditOpen(false)}
          onSaved={handleSaved}
        />
      ) : null}

      {isOwner ? (
        <SharePlaylistDialog
          open={shareOpen}
          playlist={detail}
          onClose={() => setShareOpen(false)}
        />
      ) : null}

      {isOwner ? (
        <TrackEditDialog
          open={editingTrack !== null}
          track={editingTrack}
          onClose={() => setEditingTrack(null)}
          onSaved={handleTrackSaved}
        />
      ) : null}

      {isOwner ? (
        <ConfirmDialog
          open={deleteOpen}
          title="Voleu eliminar la llista de reproducció?"
          message={
            <>
              S’eliminarà{" "}
              <span className="font-medium text-on-surface">{detail.name}</span>.
              Les cançons continuen a la vostra biblioteca; els fitxers
              multimèdia compartits no s’eliminen.
            </>
          }
          confirmLabel={deleting ? "Eliminant…" : "Elimina"}
          onConfirm={() => void confirmDelete()}
          onCancel={() => {
            if (!deleting) setDeleteOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function PlaylistTrackRow({
  track,
  index,
  total,
  queue,
  reordering,
  removing,
  readOnly,
  onMoveUp,
  onMoveDown,
  onRemove,
  onEdit,
}: {
  track: Track;
  index: number;
  total: number;
  /** Tracks in playlist order, used as the player queue. */
  queue: Track[];
  reordering: boolean;
  removing: boolean;
  /** Shared playlists are read-only: no reorder, remove or edit controls. */
  readOnly: boolean;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  onEdit: () => void;
}) {
  const { current, isPlaying, playTrack, togglePlay } = usePlayer();
  const playerActive = current?.id === track.id;
  const playerPlaying = playerActive && isPlaying;
  // A custom cover is already signed; otherwise use the track's signed
  // thumbnail and only mint a token when neither is present.
  const { token } = useMediaToken(
    track.cover_url || track.thumbnail_url || !track.thumbnail_path
      ? null
      : track.asset_id,
  );
  const src =
    track.cover_url ?? track.thumbnail_url ?? token?.thumbnail_url ?? null;
  const credit = trackCredit(track);
  const mediaType = mediaTypeFor(track);
  const isImage = mediaType === "image";
  const toast = useToast();
  const [downloading, setDownloading] = useState(false);

  async function handleDownload() {
    if (downloading || !track.asset_id) return;
    setDownloading(true);
    try {
      const fresh = await getMediaToken(track.asset_id);
      if (!fresh?.url) {
        toast("No s’ha pogut preparar el fitxer per descarregar.", "error");
        return;
      }
      triggerDownload(withDownloadFlag(fresh.url));
    } catch (e) {
      toast(
        e instanceof Error
          ? e.message
          : "No s’ha pogut preparar el fitxer per descarregar.",
        "error",
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-3 p-3 sm:p-4">
      <span className="w-6 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
        {index + 1}
      </span>
      <Thumbnail src={src} icon={trackIcon(track)} className="h-12 w-12" />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-body-large text-on-surface">
            {track.title}
          </p>
          {playerActive ? <NowPlayingIndicator /> : null}
        </div>
        <p className="mt-0.5 flex items-center gap-2 truncate text-label-medium text-on-surface-variant">
          {track.duration_seconds ? (
            <span className="tabular-nums">
              {formatDuration(track.duration_seconds)}
            </span>
          ) : null}
          {credit ? <span className="truncate">{credit}</span> : null}
        </p>
      </div>
      <div className="flex w-full items-center justify-end gap-1 sm:w-auto">
        {!readOnly ? (
          <>
            <IconButton
              label="Mou amunt"
              onClick={onMoveUp}
              disabled={index === 0 || reordering || removing}
            >
              <Icon name="arrow_upward" className="text-[20px]" />
            </IconButton>
            <IconButton
              label="Mou avall"
              onClick={onMoveDown}
              disabled={index === total - 1 || reordering || removing}
            >
              <Icon name="arrow_downward" className="text-[20px]" />
            </IconButton>
          </>
        ) : null}
        {!isImage ? (
          <>
            <OfflineButton
              assetId={track.asset_id}
              title={track.title}
              kind={mediaType === "audio" ? "audio" : "video"}
            />
            <IconButton
              variant="tonal"
              label="Descarrega el fitxer"
              onClick={() => void handleDownload()}
              disabled={downloading}
            >
              {downloading ? (
                <Spinner className="text-[20px]" />
              ) : (
                <Icon name="download" className="text-[20px]" />
              )}
            </IconButton>
          </>
        ) : null}
        <IconButton
          variant={playerActive ? "filled" : "tonal"}
          label={playerPlaying ? "Pausa" : "Reprodueix"}
          onClick={() =>
            playerActive ? togglePlay() : playTrack(track, queue)
          }
        >
          <Icon
            name={playerPlaying ? "pause" : "play_arrow"}
            className="text-[20px]"
          />
        </IconButton>
        {!readOnly ? (
          <>
            <IconButton
              variant="danger"
              label="Treu de la llista"
              onClick={onRemove}
              disabled={removing}
            >
              {removing ? (
                <Spinner className="text-[20px]" />
              ) : (
                <Icon name="playlist_remove" className="text-[20px]" />
              )}
            </IconButton>
            <Menu
              label="Més accions"
              actions={[
                {
                  id: "edit",
                  label: "Edita els detalls",
                  icon: "edit",
                  onSelect: onEdit,
                },
              ]}
            />
          </>
        ) : null}
      </div>
    </li>
  );
}
