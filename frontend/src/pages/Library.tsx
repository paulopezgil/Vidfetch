import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type {
  DownloadJob,
  LibraryItem,
  PlaylistV2,
} from "../types/v2";
import { formatBytes, formatDate } from "../lib";
import {
  deletePlaylist,
  downloadPlaylistZip,
  getMediaToken,
  listLibrary,
  listPlaylists,
  removeFromLibrary,
  triggerDownload,
  withDownloadFlag,
} from "../lib/api";
import Thumbnail from "../components/Thumbnail";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import IconButton from "../components/IconButton";
import Icon from "../components/Icon";
import Card from "../components/Card";
import FilterChip from "../components/FilterChip";
import Spinner from "../components/Spinner";
import ConfirmDialog from "../components/ConfirmDialog";
import MediaPreviewDialog from "../components/MediaPreviewDialog";
import JobCard from "../components/JobCard";
import Button from "../components/Button";
import StatusChip from "../components/StatusChip";
import { useToast } from "../components/Toast";
import { useDownloads } from "../downloads/DownloadsProvider";
import { useMediaToken } from "../lib/useMediaToken";

type Tab = "all" | "videos" | "audio" | "images" | "playlists";
type MediaType = "video" | "audio" | "image";

const PAGE = 20;
const PLAYLIST_LIMIT = 100;
/** Finished jobs stay in the "completed recently" strip for this long. */
const RECENT_WINDOW_MS = 10 * 60 * 1000;

const tabs: { value: Tab; label: string }[] = [
  { value: "all", label: "Tot" },
  { value: "videos", label: "Vídeos" },
  { value: "audio", label: "Àudio" },
  { value: "images", label: "Imatges" },
  { value: "playlists", label: "Llistes" },
];

const AUDIO_EXTENSIONS = new Set([
  "mp3",
  "m4a",
  "aac",
  "wav",
  "flac",
  "ogg",
  "opus",
]);

const IMAGE_EXTENSIONS = new Set([
  "jpg",
  "jpeg",
  "png",
  "webp",
  "gif",
  "avif",
  "bmp",
]);

interface PreviewState {
  title: string;
  mediaType: MediaType;
  src: string;
}

function extensionOf(item: LibraryItem): string {
  return item.output_ext.replace(/^\./, "").toLowerCase();
}

function mediaTypeFor(item: LibraryItem): MediaType {
  const ext = extensionOf(item);
  if (AUDIO_EXTENSIONS.has(ext)) return "audio";
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  return "video";
}

/** Human label for the stored yt-dlp selector. */
function formatLabel(selector: string): string {
  const value = selector.toLowerCase();
  if (value.includes("bestaudio") || value.includes("mp3")) return "Àudio";
  if (value.includes("720")) return "720p";
  return "Millor qualitat";
}

function isRecentJob(job: DownloadJob): boolean {
  const stamp = job.completed_at ?? job.updated_at;
  const time = Date.parse(stamp);
  return Number.isFinite(time) && Date.now() - time < RECENT_WINDOW_MS;
}

export default function Library() {
  const toast = useToast();
  const { activeJobs, finishedJobs, cancelJob, jobs } = useDownloads();
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [playlists, setPlaylists] = useState<PlaylistV2[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [pendingDelete, setPendingDelete] = useState<{
    kind: "file" | "playlist";
    id: string;
    label: string;
  } | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [libraryPage, playlistPage] = await Promise.all([
        listLibrary({ limit: PAGE, offset }),
        listPlaylists({ limit: PLAYLIST_LIMIT, offset: 0 }),
      ]);
      setItems(libraryPage.items);
      setTotal(libraryPage.total);
      setPlaylists(playlistPage.items);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut carregar la biblioteca.",
      );
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Reload the library whenever a download reaches `ready`, so the new asset
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

  const recentFinished = useMemo(
    () =>
      finishedJobs
        .filter(
          (job) => job.status === "ready" || job.status === "failed",
        )
        .filter(isRecentJob)
        .slice(0, 3),
    [finishedJobs],
  );

  async function confirmDelete() {
    if (!pendingDelete) return;
    try {
      if (pendingDelete.kind === "file") {
        await removeFromLibrary(pendingDelete.id);
        toast("Element tret de la biblioteca", "success");
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

  const openPreview = useCallback(
    async (item: LibraryItem) => {
      try {
        const token = await getMediaToken(item.asset_id);
        setPreview({
          title: item.title,
          mediaType: mediaTypeFor(item),
          src: token.url,
        });
      } catch (e) {
        toast(
          e instanceof Error
            ? e.message
            : "No s’ha pogut obrir el fitxer multimèdia.",
          "error",
        );
      }
    },
    [toast],
  );

  // Items downloaded as part of a playlist are reachable through the playlist
  // detail view; keep them out of the individual-file sections.
  const individualItems = useMemo(
    () => items.filter((item) => !item.playlist_id),
    [items],
  );
  const videoItems = individualItems.filter(
    (item) => mediaTypeFor(item) === "video",
  );
  const audioItems = individualItems.filter(
    (item) => mediaTypeFor(item) === "audio",
  );
  const imageItems = individualItems.filter(
    (item) => mediaTypeFor(item) === "image",
  );

  const visibleVideos = tab === "all" || tab === "videos" ? videoItems : [];
  const visibleAudio = tab === "all" || tab === "audio" ? audioItems : [];
  const visibleImages = tab === "all" || tab === "images" ? imageItems : [];
  const visiblePlaylists =
    tab === "all" || tab === "playlists" ? playlists : [];

  const isEmpty =
    visibleVideos.length === 0 &&
    visibleAudio.length === 0 &&
    visibleImages.length === 0 &&
    visiblePlaylists.length === 0;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      {activeJobs.length > 0 || recentFinished.length > 0 ? (
        <section className="space-y-3">
          <h2 className="px-1 text-title-medium text-on-surface">
            Descàrregues
          </h2>
          {activeJobs.length > 0 ? (
            <div className="space-y-3">
              {activeJobs.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  onCancel={async (jobId) => {
                    await cancelJob(jobId);
                  }}
                />
              ))}
            </div>
          ) : null}
          {recentFinished.length > 0 ? (
            <div className="space-y-2">
              <h3 className="px-1 text-label-large text-on-surface-variant">
                Acabades fa poc
              </h3>
              <div className="space-y-3">
                {recentFinished.map((job) => (
                  <JobCard key={job.id} job={job} />
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
          <Spinner /> S’està carregant la biblioteca…
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

          {visibleVideos.length > 0 ? (
            <section className="space-y-2">
              {tab === "all" ? (
                <h2 className="px-1 text-title-medium text-on-surface">
                  Vídeos
                </h2>
              ) : null}
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {visibleVideos.map((item) => (
                  <FileRow
                    key={item.job_id}
                    item={item}
                    onPreview={() => void openPreview(item)}
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
          ) : null}

          {visibleAudio.length > 0 ? (
            <section className="space-y-2">
              {tab === "all" ? (
                <h2 className="px-1 text-title-medium text-on-surface">
                  Àudio
                </h2>
              ) : null}
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {visibleAudio.map((item) => (
                  <FileRow
                    key={item.job_id}
                    item={item}
                    onPreview={() => void openPreview(item)}
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
          ) : null}

          {visibleImages.length > 0 ? (
            <section className="space-y-2">
              {tab === "all" ? (
                <h2 className="px-1 text-title-medium text-on-surface">
                  Imatges
                </h2>
              ) : null}
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {visibleImages.map((item) => (
                  <FileRow
                    key={item.job_id}
                    item={item}
                    onPreview={() => void openPreview(item)}
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
          ) : null}

          {!error && isEmpty ? (
            <EmptyState
              icon="folder_open"
              title={
                tab === "all" ? "La biblioteca és buida" : "Aquí no hi ha res"
              }
              description={
                tab === "all"
                  ? "Els vídeos i les llistes de reproducció que descarreguis apareixeran aquí."
                  : "Prova un altre filtre o descarrega contingut nou des de l’Inici."
              }
            />
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
            ? "Voleu treure el fitxer de la biblioteca?"
            : "Voleu eliminar la llista de reproducció?"
        }
        message={
          pendingDelete?.kind === "file" ? (
            <>
              S’amagarà{" "}
              <span className="font-medium text-on-surface">
                {pendingDelete.label}
              </span>{" "}
              de la vostra biblioteca. El fitxer compartit no s’elimina i la
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

      <MediaPreviewDialog
        open={preview !== null}
        title={preview?.title ?? ""}
        mediaType={preview?.mediaType ?? "video"}
        src={preview?.src ?? ""}
        onClose={() => setPreview(null)}
      />
    </div>
  );
}

function FileRow({
  item,
  onDelete,
  onPreview,
}: {
  item: LibraryItem;
  onDelete: () => void;
  onPreview: () => void;
}) {
  const toast = useToast();
  const mediaType = mediaTypeFor(item);
  const isImage = mediaType === "image";
  const icon =
    mediaType === "audio" ? "music_note" : isImage ? "image" : "movie";
  const { token, refresh: refreshToken } = useMediaToken(item.asset_id);
  const [downloading, setDownloading] = useState(false);
  const ext = extensionOf(item);

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
        src={token?.thumbnail_url ?? null}
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
          {formatBytes(item.file_size_bytes)} ·{" "}
          {(ext || "fitxer").toUpperCase()} ·{" "}
          {formatLabel(item.format_selector)} · {formatDate(item.created_at)}
        </p>
      </div>
      <div className="flex w-full items-center gap-1.5 sm:w-auto">
        <IconButton
          variant="tonal"
          label={isImage ? "Mostra la imatge" : "Reprodueix"}
          onClick={onPreview}
        >
          <Icon
            name={isImage ? "image" : "play_arrow"}
            className="text-[20px]"
          />
        </IconButton>
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
          label="Treu el fitxer de la biblioteca"
          onClick={onDelete}
        >
          <Icon name="delete" className="text-[20px]" />
        </IconButton>
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
          to={`/library/playlist/${playlist.id}`}
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
