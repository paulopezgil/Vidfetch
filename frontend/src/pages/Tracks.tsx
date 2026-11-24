import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { PlaylistV2, Track } from "../types/v2";
import { formatBytes, formatDate } from "../lib";
import {
  deletePlaylist,
  downloadPlaylistZip,
  listPlaylists,
  listTracks,
  removeFromLibrary,
  triggerDownload,
  withDownloadFlag,
} from "../lib/api";
import { extensionOf, groupTracksByDay, mediaTypeFor } from "../lib/trackDisplay";
import Thumbnail from "../components/Thumbnail";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import IconButton from "../components/IconButton";
import Icon from "../components/Icon";
import Card from "../components/Card";
import FilterChip from "../components/FilterChip";
import Spinner from "../components/Spinner";
import ConfirmDialog from "../components/ConfirmDialog";
import Menu from "../components/Menu";
import AddToPlaylistDialog from "../components/AddToPlaylistDialog";
import TrackEditDialog from "../components/TrackEditDialog";
import SearchBar from "../components/SearchBar";
import Button from "../components/Button";
import StatusChip from "../components/StatusChip";
import OfflineButton from "../components/OfflineButton";
import { useToast } from "../components/Toast";
import { useDownloads } from "../downloads/DownloadsProvider";
import { useMediaToken } from "../lib/useMediaToken";
import { usePlayer } from "../player/PlayerProvider";

type Tab = "all" | "videos" | "audio" | "playlists";

const PAGE = 20;
const PLAYLIST_LIMIT = 100;

const tabs: { value: Tab; label: string }[] = [
  { value: "all", label: "Tot" },
  { value: "videos", label: "Vídeos" },
  { value: "audio", label: "Àudio" },
  { value: "playlists", label: "Llistes" },
];

/** Human label for the stored yt-dlp selector. */
function formatLabel(selector: string): string {
  const value = selector.toLowerCase();
  if (value.includes("bestaudio") || value.includes("mp3")) return "Àudio";
  if (value.includes("720")) return "720p";
  return "Millor qualitat";
}

export default function Tracks() {
  const toast = useToast();
  const { jobs } = useDownloads();
  const [items, setItems] = useState<Track[]>([]);
  const [playlists, setPlaylists] = useState<PlaylistV2[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [searchInput, setSearchInput] = useState("");
  /** Trimmed query that actually reaches `GET /api/tracks`. */
  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<{
    kind: "file" | "playlist";
    id: string;
    label: string;
  } | null>(null);
  const [editing, setEditing] = useState<Track | null>(null);
  const [addTarget, setAddTarget] = useState<Track | null>(null);

  const searchActive = query.length > 0;

  const submitSearch = useCallback((value: string) => {
    const next = value.trim();
    setQuery((current) => (current === next ? current : next));
    setOffset(0);
  }, []);

  function handleSearchChange(value: string) {
    setSearchInput(value);
    // Clearing the field drops the filter immediately, without a submit.
    if (value.trim() === "" && query !== "") {
      setQuery("");
      setOffset(0);
    }
  }

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [trackPage, playlistPage] = await Promise.all([
        listTracks({ limit: PAGE, offset, q: query || undefined }),
        listPlaylists({ limit: PLAYLIST_LIMIT, offset: 0 }),
      ]);
      setItems(trackPage.items);
      setTotal(trackPage.total);
      setPlaylists(playlistPage.items);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’han pogut carregar els tracks.",
      );
    } finally {
      setLoading(false);
    }
  }, [offset, query]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Reload the tracks whenever a download reaches `ready`, so the new asset
  // appears without a manual refresh. Keep polling updates from causing a
  // reload on every tick by comparing the set of ready jobs.
  const readySignature = useMemo(
    () =>
      jobs
        .filter((job) => job.status === "ready")
        .map((job) => `${job.id}:${job.asset_id ?? ""}`)
        .sort()
        .join("|"),
    [jobs],
  );
  const previousReadyRef = useRef(readySignature);
  useEffect(() => {
    if (previousReadyRef.current === readySignature) return;
    previousReadyRef.current = readySignature;
    void refresh();
  }, [readySignature, refresh]);

  async function confirmDelete() {
    if (!pendingDelete) return;
    try {
      if (pendingDelete.kind === "file") {
        await removeFromLibrary(pendingDelete.id);
        toast("Track amagat", "success");
      } else {
        await deletePlaylist(pendingDelete.id);
        toast("Llista de reproducció eliminada", "success");
      }
      setPendingDelete(null);
      // Removing the last item on a page would leave the offset past the end.
      if (pendingDelete.kind === "file" && items.length === 1 && offset > 0) {
        setOffset(Math.max(0, offset - PAGE));
      } else {
        await refresh();
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "No s’ha pogut eliminar", "error");
    }
  }

  const handleTrackSaved = useCallback(
    (updated: Track) => {
      // Update the row immediately, then reload so totals and signed cover
      // URLs come from the API.
      setItems((prev) =>
        prev.map((item) => (item.id === updated.id ? updated : item)),
      );
      toast("Track actualitzat", "success");
      void refresh();
    },
    [refresh, toast],
  );

  // Items downloaded as part of a playlist are reachable through the playlist
  // detail view; keep them out of the individual-file sections.
  const individualItems = useMemo(
    () => items.filter((item) => !item.playlist_id),
    [items],
  );

  // Apply the filter chips before grouping so every day section only holds the
  // media types the active chip allows. Images never belong to the music/video
  // library, so they are excluded from every chip, including «Tot».
  const visibleTracks = useMemo(() => {
    if (tab === "playlists") return [];
    return individualItems.filter((item) => {
      const mediaType = mediaTypeFor(item);
      if (mediaType === "image") return false;
      if (tab === "videos") return mediaType === "video";
      if (tab === "audio") return mediaType === "audio";
      return true;
    });
  }, [individualItems, tab]);

  const trackDays = useMemo(
    () => groupTracksByDay(visibleTracks),
    [visibleTracks],
  );

  const visiblePlaylists = useMemo(() => {
    if (tab !== "all" && tab !== "playlists") return [];
    if (!searchActive) return playlists;
    const needle = query.toLocaleLowerCase("ca-ES");
    return playlists.filter((playlist) =>
      playlist.title.toLocaleLowerCase("ca-ES").includes(needle),
    );
  }, [tab, playlists, searchActive, query]);

  const isEmpty = visibleTracks.length === 0 && visiblePlaylists.length === 0;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      <SearchBar
        value={searchInput}
        onChange={handleSearchChange}
        onSubmit={() => submitSearch(searchInput)}
        label="Cerca tracks"
        placeholder="Cerca per títol, artista o àlbum"
        loading={loading}
      />

      {loading ? (
        <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
          <Spinner /> S’estan carregant els tracks…
        </div>
      ) : (
        <>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {tabs.map((t) => (
              <FilterChip
                key={t.value}
                label={t.label}
                selected={tab === t.value}
                onClick={() => setTab(t.value)}
              />
            ))}
          </div>

          {visiblePlaylists.length > 0 ? (
            <section className="space-y-2">
              {tab === "all" ? (
                <h2 className="px-1 text-title-medium text-on-surface">
                  Llistes de reproducció
                </h2>
              ) : null}
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {visiblePlaylists.map((playlist) => (
                  <PlaylistRow
                    key={playlist.id}
                    playlist={playlist}
                    onDelete={() =>
                      setPendingDelete({
                        kind: "playlist",
                        id: playlist.id,
                        label: playlist.title,
                      })
                    }
                  />
                ))}
              </Card>
            </section>
          ) : null}

          {trackDays.map((day) => (
            <section key={day.key} className="space-y-2">
              <h2 className="px-1 text-title-medium text-on-surface">
                {day.label}
              </h2>
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {day.items.map((item) => (
                  <FileRow
                    key={item.job_id}
                    item={item}
                    queue={day.items}
                    onEdit={() => setEditing(item)}
                    onAddToPlaylist={() => setAddTarget(item)}
                    onDelete={() =>
                      setPendingDelete({
                        kind: "file",
                        id: item.job_id,
                        label: item.title,
                      })
                    }
                  />
                ))}
              </Card>
            </section>
          ))}

          {!error && isEmpty ? (
            searchActive ? (
              <EmptyState
                icon="search_off"
                title="Cap resultat per a la cerca"
                description={`No hi ha cap track que coincideixi amb «${query}». Prova un altre terme o neteja la cerca.`}
              />
            ) : (
              <EmptyState
                icon="folder_open"
                title={
                  tab === "all" ? "Encara no hi ha tracks" : "Aquí no hi ha res"
                }
                description={
                  tab === "all"
                    ? "Els vídeos i les llistes de reproducció que descarreguis apareixeran aquí."
                    : "Prova un altre filtre o descarrega contingut nou des de l’Inici."
                }
              />
            )
          ) : null}

          {total > PAGE && tab !== "playlists" ? (
            <div className="flex items-center justify-between text-body-medium text-on-surface-variant">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, total)} de {total}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outlined"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                >
                  Anterior
                </Button>
                <Button
                  variant="outlined"
                  size="sm"
                  disabled={offset + PAGE >= total}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  Següent
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={
          pendingDelete?.kind === "file"
            ? "Voleu treure el track?"
            : "Voleu eliminar la llista de reproducció?"
        }
        message={
          pendingDelete?.kind === "file" ? (
            <>
              S’amagarà{" "}
              <span className="font-medium text-on-surface">
                {pendingDelete.label}
              </span>{" "}
              dels vostres tracks. El fitxer compartit no s’elimina i la
              descàrrega es conserva a l’historial.
            </>
          ) : (
            <>
              S’eliminarà{" "}
              <span className="font-medium text-on-surface">
                {pendingDelete?.label}
              </span>{" "}
              i els seus elements. Els fitxers multimèdia compartits no
              s’eliminen.
            </>
          )
        }
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      <TrackEditDialog
        open={editing !== null}
        track={editing}
        onClose={() => setEditing(null)}
        onSaved={handleTrackSaved}
      />

      <AddToPlaylistDialog
        open={addTarget !== null}
        track={addTarget}
        onClose={() => setAddTarget(null)}
      />
    </div>
  );
}

function FileRow({
  item,
  queue,
  onDelete,
  onEdit,
  onAddToPlaylist,
}: {
  item: Track;
  /** Visible rows that form the play queue for this section. */
  queue: Track[];
  onDelete: () => void;
  onEdit: () => void;
  onAddToPlaylist: () => void;
}) {
  const toast = useToast();
  const { current, isPlaying, playTrack, togglePlay } = usePlayer();
  const playerActive = current?.id === item.id;
  const playerPlaying = playerActive && isPlaying;
  const mediaType = mediaTypeFor(item);
  const icon = mediaType === "audio" ? "music_note" : "movie";
  const { token, refresh: refreshToken } = useMediaToken(item.asset_id);
  const [downloading, setDownloading] = useState(false);
  const ext = extensionOf(item);
  const credit = [item.artist, item.album]
    .map((value) => value.trim())
    .filter((value) => value.length > 0)
    .join(" · ");

  async function handleDownload() {
    if (downloading) return;
    setDownloading(true);
    try {
      // Never reuse a thumbnail token for a download: tokens are short-lived.
      const fresh = await refreshToken();
      if (!fresh) {
        toast("No s’ha pogut preparar el fitxer per descarregar.", "error");
        return;
      }
      triggerDownload(withDownloadFlag(fresh.url));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 p-4">
      <Thumbnail
        src={item.cover_url ?? token?.thumbnail_url ?? null}
        icon={icon}
        className="aspect-video w-20"
      />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-title-small text-on-surface">
            {item.title}
          </p>
          <StatusChip status={item.status} />
        </div>
        <p className="mt-0.5 text-body-small text-on-surface-variant">
          {formatBytes(item.file_size_bytes ?? 0)} ·{" "}
          {(ext || "fitxer").toUpperCase()} ·{" "}
          {credit ? `${credit} · ` : ""}
          {formatLabel(item.format_selector)} · {formatDate(item.downloaded_at)}
        </p>
      </div>
      <div className="flex w-full items-center gap-1.5 sm:w-auto">
        <IconButton
          variant={playerActive ? "filled" : "tonal"}
          label={playerPlaying ? "Pausa" : "Reprodueix"}
          onClick={() => (playerActive ? togglePlay() : playTrack(item, queue))}
        >
          <Icon
            name={playerPlaying ? "pause" : "play_arrow"}
            className="text-[20px]"
          />
        </IconButton>
        {mediaType === "audio" ? (
          // Songs use the offline-state control instead of a one-shot file
          // download: the second phase of an audio job is automatic.
          <OfflineButton assetId={item.asset_id} title={item.title} />
        ) : (
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
        )}
        <IconButton variant="danger" label="Treu el track" onClick={onDelete}>
          <Icon name="delete" className="text-[20px]" />
        </IconButton>
        <Menu
          label="Més accions"
          actions={[
            {
              id: "add-to-playlist",
              label: "Afegeix a una playlist",
              icon: "playlist_add",
              onSelect: onAddToPlaylist,
            },
            {
              id: "edit",
              label: "Edita els detalls",
              icon: "edit",
              onSelect: onEdit,
            },
          ]}
        />
      </div>
    </div>
  );
}

function PlaylistRow({
  playlist,
  onDelete,
}: {
  playlist: PlaylistV2;
  onDelete: () => void;
}) {
  const toast = useToast();
  const [zipping, setZipping] = useState(false);
  const canZip =
    playlist.status === "ready" || playlist.status === "partial";

  async function handleZip() {
    if (zipping) return;
    setZipping(true);
    try {
      await downloadPlaylistZip(
        playlist.id,
        `${playlist.title || "playlist"}.zip`,
      );
    } catch (e) {
      toast(
        e instanceof Error
          ? e.message
          : "No s’ha pogut descarregar el ZIP.",
        "error",
      );
    } finally {
      setZipping(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 p-4 sm:gap-4">
      <Thumbnail
        src={playlist.thumbnail_url ?? null}
        icon="playlist_play"
        className="aspect-video w-24"
      />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-title-small text-on-surface">
            {playlist.title}
          </p>
          <StatusChip status={playlist.status} />
        </div>
        <p className="mt-0.5 text-body-small text-on-surface-variant">
          {playlist.item_count} vídeos ·{" "}
          {formatLabel(playlist.format_selector)}
        </p>
      </div>
      <div className="flex w-full items-center gap-1.5 sm:w-auto">
        <Link
          to={`/imported/${playlist.id}`}
          className="inline-flex h-9 items-center gap-1.5 rounded-full bg-secondary-container px-4 text-label-large text-on-secondary-container transition-colors hover:bg-secondary-container/90"
        >
          <Icon name="folder_open" className="text-[18px]" /> Mostra
        </Link>
        {canZip ? (
          <Button
            variant="outlined"
            size="sm"
            onClick={() => void handleZip()}
            disabled={zipping}
          >
            {zipping ? (
              <Spinner className="text-[18px]" />
            ) : (
              <Icon name="folder_zip" className="text-[18px]" />
            )}
            ZIP
          </Button>
        ) : null}
        <IconButton
          variant="danger"
          label="Elimina la llista de reproducció"
          onClick={onDelete}
        >
          <Icon name="delete" className="text-[20px]" />
        </IconButton>
      </div>
    </div>
  );
}
