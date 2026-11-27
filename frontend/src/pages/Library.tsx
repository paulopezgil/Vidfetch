import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Track } from "../types/v2";
import { formatBytes, formatDate } from "../lib";
import {
  listTracks,
  removeFromLibrary,
  triggerDownload,
  withDownloadFlag,
} from "../lib/api";
import {
  extensionOf,
  groupTracksByDay,
  mediaTypeFor,
} from "../lib/trackDisplay";
import Thumbnail from "../components/Thumbnail";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import IconButton from "../components/IconButton";
import Icon from "../components/Icon";
import Card from "../components/Card";
import Spinner from "../components/Spinner";
import ConfirmDialog from "../components/ConfirmDialog";
import Menu from "../components/Menu";
import NowPlayingIndicator from "../components/NowPlayingIndicator";
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

/** Which half of the library this page renders. */
export type LibraryKind = "audio" | "video";

type SortMode = "downloaded" | "title";

const PAGE = 20;
const SORT_STORAGE_KEY = "vidfetch.librarySort";

interface LibraryGroup {
  key: string;
  label: string | null;
  items: Track[];
}

/** Human label for the stored yt-dlp selector. */
function formatLabel(selector: string): string {
  const value = selector.toLowerCase();
  if (value.includes("bestaudio") || value.includes("mp3")) return "Àudio";
  if (value.includes("720")) return "720p";
  return "Millor qualitat";
}

/** Restore the shared sort preference; a bad store falls back to newest first. */
function initialSort(): SortMode {
  try {
    return window.localStorage.getItem(SORT_STORAGE_KEY) === "title"
      ? "title"
      : "downloaded";
  } catch {
    return "downloaded";
  }
}

export default function Library({ kind }: { kind: LibraryKind }) {
  const toast = useToast();
  const { jobs } = useDownloads();
  const { updateTrack } = usePlayer();
  const [items, setItems] = useState<Track[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortMode>(initialSort);
  const [searchInput, setSearchInput] = useState("");
  /** Trimmed query that actually reaches `GET /api/tracks`. */
  const [query, setQuery] = useState("");
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    label: string;
  } | null>(null);
  const [editing, setEditing] = useState<Track | null>(null);
  const [addTarget, setAddTarget] = useState<Track | null>(null);

  const searchActive = query.length > 0;
  const noun = kind === "audio" ? "cançons" : "vídeos";
  const nounSingular = kind === "audio" ? "cançó" : "vídeo";
  const nounTitle = kind === "audio" ? "cançons" : "vídeos";

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

  const changeSort = useCallback(
    (next: SortMode) => {
      if (next === sort) return;
      setSort(next);
      setOffset(0);
      try {
        window.localStorage.setItem(SORT_STORAGE_KEY, next);
      } catch {
        // A blocked localStorage still keeps the in-memory preference.
      }
    },
    [sort],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const trackPage = await listTracks({
        limit: PAGE,
        offset,
        q: query || undefined,
        sort,
      });
      setItems(trackPage.items);
      setTotal(trackPage.total);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : `No s’han pogut carregar les ${noun}.`,
      );
    } finally {
      setLoading(false);
    }
  }, [noun, offset, query, sort]);

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
      await removeFromLibrary(pendingDelete.id);
      toast("Tret de la biblioteca", "success");
      setPendingDelete(null);
      // Removing the last item on a page would leave the offset past the end.
      if (items.length === 1 && offset > 0) {
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
      // Keep the docked/full-screen player in step when this row is playing.
      updateTrack(updated);
      toast("Cançó actualitzada", "success");
      void refresh();
    },
    [refresh, toast, updateTrack],
  );

  // Playlist downloads produce normal per-user tracks too, so they belong to
  // the song/video sections like any other download. The destination selects
  // the media kind, and images never belong to either list.
  const visibleTracks = useMemo(() => {
    const matching = items.filter((item) => mediaTypeFor(item) === kind);
    if (sort === "title") {
      return [...matching].sort((a, b) =>
        a.title.localeCompare(b.title, "ca", { sensitivity: "base" }),
      );
    }
    return matching;
  }, [items, kind, sort]);

  // Newest-first keeps the familiar Avui/Ahir/date sections. A–Z is one flat
  // list without day headings.
  const groups = useMemo<LibraryGroup[]>(() => {
    if (sort === "title") {
      return [{ key: "title", label: null, items: visibleTracks }];
    }
    return groupTracksByDay(visibleTracks);
  }, [sort, visibleTracks]);

  const isEmpty = visibleTracks.length === 0;
  const sortLabel =
    sort === "title" ? "Títol (A–Z)" : "Data de descàrrega";

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      <div className="flex items-center gap-2">
        <SearchBar
          className="min-w-0 flex-1"
          value={searchInput}
          onChange={handleSearchChange}
          onSubmit={() => submitSearch(searchInput)}
          label={`Cerca ${noun}`}
          placeholder="Cerca per títol, artista o àlbum"
          loading={loading}
        />
        <Menu
          label={`Ordena per: ${sortLabel}`}
          icon="sort"
          disabled={loading}
          actions={[
            {
              id: "downloaded",
              label: "Data de descàrrega",
              icon: "calendar_today",
              selected: sort === "downloaded",
              onSelect: () => changeSort("downloaded"),
            },
            {
              id: "title",
              label: "Títol (A–Z)",
              icon: "sort_by_alpha",
              selected: sort === "title",
              onSelect: () => changeSort("title"),
            },
          ]}
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
          <Spinner /> S’estan carregant les {noun}…
        </div>
      ) : (
        <>
          {groups.map((group) => (
            <section key={group.key} className="space-y-2">
              {group.label ? (
                <h2 className="px-1 text-title-medium text-on-surface">
                  {group.label}
                </h2>
              ) : null}
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {group.items.map((item) => (
                  <FileRow
                    key={item.job_id}
                    item={item}
                    queue={group.items}
                    onEdit={() => setEditing(item)}
                    onAddToPlaylist={() => setAddTarget(item)}
                    onDelete={() =>
                      setPendingDelete({
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
                description={`No hi ha cap ${nounSingular} que coincideixi amb «${query}». Prova un altre terme o neteja la cerca.`}
              />
            ) : (
              <EmptyState
                icon={kind === "audio" ? "music_note" : "movie"}
                title={`Encara no hi ha ${nounTitle}`}
                description={
                  kind === "audio"
                    ? "Les cançons que descarreguis apareixeran aquí."
                    : "Els vídeos que descarreguis apareixeran aquí."
                }
              />
            )
          ) : null}

          {total > PAGE ? (
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
        title="Voleu treure aquest element?"
        message={
          <>
            S’amagarà{" "}
            <span className="font-medium text-on-surface">
              {pendingDelete?.label}
            </span>{" "}
            dels vostres {noun}. El fitxer compartit no s’elimina i la
            descàrrega es conserva a l’historial.
          </>
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
        src={
          item.cover_url ??
          item.thumbnail_url ??
          token?.thumbnail_url ??
          null
        }
        icon={icon}
        className="aspect-video w-20"
      />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-title-small text-on-surface">
            {item.title}
          </p>
          {playerActive ? (
            <NowPlayingIndicator />
          ) : item.status !== "ready" ? (
            <StatusChip status={item.status} />
          ) : null}
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
        <OfflineButton
          assetId={item.asset_id}
          title={item.title}
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
        <IconButton
          variant="danger"
          label="Treu de la biblioteca"
          onClick={onDelete}
        >
          <Icon name="delete" className="text-[20px]" />
        </IconButton>
        <Menu
          label="Més accions"
          actions={[
            {
              id: "add-to-playlist",
              label: "Afegeix a una llista",
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
