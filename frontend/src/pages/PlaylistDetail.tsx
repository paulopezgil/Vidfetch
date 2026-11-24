import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type {
  CreateDownloadPayload,
  DownloadFormat,
  PlaylistDetailV2,
  PlaylistItemV2,
} from "../types/v2";
import { formatDuration } from "../lib";
import {
  deletePlaylist,
  downloadPlaylistZip,
  getMediaToken,
  getPlaylist,
  triggerDownload,
  withDownloadFlag,
} from "../lib/api";
import Button from "../components/Button";
import Thumbnail from "../components/Thumbnail";
import ProgressBar from "../components/ProgressBar";
import StatusChip from "../components/StatusChip";
import IconButton from "../components/IconButton";
import Icon from "../components/Icon";
import Card from "../components/Card";
import SegmentedButton from "../components/SegmentedButton";
import Switch from "../components/Switch";
import Spinner from "../components/Spinner";
import EmptyState from "../components/EmptyState";
import MediaPreviewDialog from "../components/MediaPreviewDialog";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { useDownloads } from "../downloads/DownloadsProvider";
import { useMediaToken } from "../lib/useMediaToken";
import { setActivePlaylistTitle } from "../navigation";

const formatOptions = [
  { value: "best", label: "Millor qualitat", icon: "high_quality" },
  { value: "720p", label: "720p", icon: "hd" },
  { value: "mp3", label: "MP3", icon: "music_note" },
];

function formatFromSelector(selector: string): DownloadFormat {
  const value = selector.toLowerCase();
  if (value.includes("bestaudio") || value.includes("mp3")) return "mp3";
  if (value.includes("720")) return "720p";
  return "best";
}

/** Playlist items inherit the audio/video nature of the playlist's format. */
function mediaTypeForSelector(
  formatSelector: string,
): "video" | "audio" {
  const selector = formatSelector.toLowerCase();
  if (selector.includes("bestaudio") || selector.includes("mp3")) {
    return "audio";
  }
  return "video";
}

interface PreviewState {
  title: string;
  mediaType: "video" | "audio";
  src: string;
}

export default function PlaylistDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { activeJobs, createJob } = useDownloads();
  const [detail, setDetail] = useState<PlaylistDetailV2 | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<DownloadFormat>("best");
  const [embedSubs, setEmbedSubs] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [zipBusy, setZipBusy] = useState(false);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  // Polling refreshes the whole detail view. Guard the stored-format sync so
  // that a refresh never overwrites a selection the user is making: apply the
  // persisted format on first load and when the route changes playlist.
  const appliedPlaylistRef = useRef<string | null>(null);
  const formatTouchedRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      setDetail(await getPlaylist(id));
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
    void refresh();
  }, [refresh]);

  // Publish the loaded playlist name for the top app bar title.
  useEffect(() => {
    setActivePlaylistTitle(null);
  }, [id]);

  useEffect(() => {
    setActivePlaylistTitle(detail?.title ?? null);
  }, [detail]);

  useEffect(() => () => setActivePlaylistTitle(null), []);

  useEffect(() => {
    if (!detail) return;
    if (appliedPlaylistRef.current !== detail.id) {
      appliedPlaylistRef.current = detail.id;
      formatTouchedRef.current = false;
    }
    if (!formatTouchedRef.current) {
      setFormat(formatFromSelector(detail.format_selector));
    }
  }, [detail]);

  const activeSourceUrls = useMemo(
    () => new Set(activeJobs.map((job) => job.source_url)),
    [activeJobs],
  );

  const playlistJobActive = detail
    ? activeJobs.some(
        (job) =>
          job.source_url === detail.source_url || job.playlist_id === detail.id,
      )
    : false;
  const itemJobActive =
    detail?.items.some((item) => activeSourceUrls.has(item.source_url)) ??
    false;
  const downloadingItems =
    detail?.items.some((item) => item.status === "downloading") ?? false;
  const shouldPoll =
    playlistJobActive ||
    itemJobActive ||
    downloadingItems ||
    detail?.status === "downloading";

  useEffect(() => {
    if (!shouldPoll) return;
    const interval = window.setInterval(() => {
      void refresh();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [shouldPoll, refresh]);

  const startJob = useCallback(
    async (payload: CreateDownloadPayload, busyKey: string) => {
      setBusy(busyKey);
      try {
        await createJob(payload);
        toast("Descàrrega iniciada", "info");
      } catch (e) {
        toast(
          e instanceof Error
            ? e.message
            : "No s’ha pogut iniciar la descàrrega",
          "error",
        );
      } finally {
        setBusy(null);
      }
    },
    [createJob, toast],
  );

  const openPreview = useCallback(
    async (item: PlaylistItemV2) => {
      if (!item.asset_id) return;
      try {
        const token = await getMediaToken(item.asset_id);
        setPreview({
          title: item.title,
          mediaType: mediaTypeForSelector(detail?.format_selector ?? ""),
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
    [detail?.format_selector, toast],
  );

  const confirmDeletePlaylist = useCallback(async () => {
    if (!detail) return;
    try {
      // Removing a playlist deletes its rows only; shared media assets stay.
      await deletePlaylist(detail.id);
      toast("Llista de reproducció eliminada", "success");
      setDeleteOpen(false);
      navigate("/playlists");
    } catch (e) {
      toast(
        e instanceof Error
          ? e.message
          : "No s’ha pogut eliminar la llista de reproducció",
        "error",
      );
    }
  }, [detail, navigate, toast]);

  const handleZip = useCallback(async () => {
    if (!detail || zipBusy) return;
    setZipBusy(true);
    try {
      await downloadPlaylistZip(
        detail.id,
        `${detail.title || "playlist"}.zip`,
      );
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "No s’ha pogut descarregar el ZIP",
        "error",
      );
    } finally {
      setZipBusy(false);
    }
  }, [detail, toast, zipBusy]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
        <Spinner /> S’està carregant la llista de reproducció…
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6 lg:px-8">
        <Link
          to="/playlists"
          className="mb-4 inline-flex items-center gap-1.5 text-label-large text-primary hover:text-primary/80"
        >
          <Icon name="arrow_back" className="text-[20px]" /> Playlists
        </Link>
        <EmptyState
          icon="playlist_remove"
          title="No s’ha trobat la llista de reproducció"
          description={error ?? "Aquesta llista de reproducció no existeix."}
        />
      </div>
    );
  }

  const items = detail.items;
  const readyCount = items.filter(
    (item) => item.status === "ready" && item.asset_id,
  ).length;
  const failedCount = items.filter((item) => item.status === "failed").length;
  const total = Math.max(detail.item_count, items.length, 1);
  const overall = Math.round((readyCount / total) * 100);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <Link
        to="/playlists"
        className="inline-flex w-fit items-center gap-1.5 rounded-full pr-3 text-label-large text-primary hover:text-primary/80"
      >
        <Icon name="arrow_back" className="text-[20px]" /> Playlists
      </Link>

      <Card variant="outlined" className="p-4 sm:p-6">
        <div className="flex flex-col gap-5 sm:flex-row">
          <Thumbnail
            src={detail.thumbnail_url ?? null}
            icon="playlist_play"
            className="aspect-video w-full sm:w-52"
          />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h1 className="text-headline-small text-on-surface">
                {detail.title}
              </h1>
              <StatusChip status={detail.status} />
              <IconButton
                variant="danger"
                label="Elimina la llista de reproducció"
                className="ml-auto"
                disabled={playlistJobActive}
                onClick={() => setDeleteOpen(true)}
              >
                <Icon name="delete" className="text-[20px]" />
              </IconButton>
            </div>
            <p className="mt-1 text-body-medium text-on-surface-variant">
              {detail.channel}
              {detail.channel ? " · " : ""}
              {detail.item_count} vídeos
            </p>

            <div className="mt-4">
              <div className="mb-1.5 flex items-center justify-between text-label-medium text-on-surface-variant">
                <span>
                  {readyCount} de {total} descarregats
                  {failedCount ? ` · ${failedCount} fallits` : ""}
                </span>
                <span className="tabular-nums">{overall}%</span>
              </div>
              <ProgressBar
                value={overall}
                label="Progrés de la descàrrega de la llista"
                status={
                  failedCount && readyCount ? "completed" : undefined
                }
              />
            </div>

            <div className="mt-5">
              <p className="mb-2 text-label-large text-on-surface-variant">
                Format
              </p>
              <SegmentedButton
                options={formatOptions}
                value={format}
                onChange={(value) => {
                  formatTouchedRef.current = true;
                  setFormat(value as DownloadFormat);
                }}
                label="Format de descàrrega"
              />
            </div>

            <div className="mt-5">
              <Switch
                checked={embedSubs && format !== "mp3"}
                onChange={setEmbedSubs}
                disabled={format === "mp3"}
                label="Incrusta els subtítols si estan disponibles"
              />
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-2">
              {readyCount > 0 ? (
                // The ZIP is built on demand by the backend and requires the
                // bearer token, so fetch it through the authenticated client
                // and save the resulting blob.
                <Button
                  onClick={() => void handleZip()}
                  disabled={zipBusy}
                  aria-label="Descarrega la llista de reproducció en un ZIP"
                >
                  {zipBusy ? (
                    <Spinner className="text-[18px]" />
                  ) : (
                    <Icon name="download" className="text-[18px]" />
                  )}
                  Descarrega la llista de reproducció
                </Button>
              ) : (
                // Nothing is downloaded yet, so there is no archive to build:
                // start the playlist download instead.
                <Button
                  onClick={() =>
                    void startJob(
                      {
                        url: detail.source_url,
                        kind: "playlist",
                        format,
                        embed_subs: embedSubs && format !== "mp3",
                      },
                      "playlist",
                    )
                  }
                  disabled={busy === "playlist" || playlistJobActive}
                >
                  {busy === "playlist" || playlistJobActive ? (
                    <Spinner className="text-[18px]" />
                  ) : (
                    <Icon name="download" className="text-[18px]" />
                  )}
                  Descarrega la llista de reproducció
                </Button>
              )}
            </div>
          </div>
        </div>
      </Card>

      {items.length > 0 ? (
        <Card
          variant="outlined"
          className="divide-y divide-outline-variant overflow-hidden"
        >
          {items.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              formatSelector={detail.format_selector}
              busy={busy === item.id || activeSourceUrls.has(item.source_url)}
              onDownload={() =>
                void startJob(
                  {
                    url: item.source_url,
                    kind: "video",
                    format,
                    embed_subs: embedSubs && format !== "mp3",
                  },
                  item.id,
                )
              }
              onPreview={() => void openPreview(item)}
            />
          ))}
        </Card>
      ) : (
        <EmptyState
          icon="playlist_play"
          title="No hi ha elements per mostrar"
          description="Aquesta llista de reproducció encara no té cap element per descarregar."
        />
      )}

      <MediaPreviewDialog
        open={preview !== null}
        title={preview?.title ?? ""}
        mediaType={preview?.mediaType ?? "video"}
        src={preview?.src ?? ""}
        onClose={() => setPreview(null)}
      />

      <ConfirmDialog
        open={deleteOpen}
        title="Voleu eliminar la llista de reproducció?"
        message={
          <>
            S’eliminarà{" "}
            <span className="font-medium text-on-surface">{detail.title}</span>{" "}
            i els seus elements. Els fitxers multimèdia compartits no
            s’eliminen i les descàrregues es conserven a l’historial.
          </>
        }
        onConfirm={confirmDeletePlaylist}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}

function ItemRow({
  item,
  formatSelector,
  busy,
  onDownload,
  onPreview,
}: {
  item: PlaylistItemV2;
  formatSelector: string;
  busy: boolean;
  onDownload: () => void;
  onPreview: () => void;
}) {
  const toast = useToast();
  const { token, refresh: refreshToken } = useMediaToken(item.asset_id);
  const [downloadingFile, setDownloadingFile] = useState(false);
  const ready = item.status === "ready" && Boolean(item.asset_id);
  const mediaType = mediaTypeForSelector(formatSelector);
  const thumbSrc = token?.thumbnail_url ?? item.thumbnail_url ?? null;

  async function handleFileDownload() {
    if (downloadingFile) return;
    setDownloadingFile(true);
    try {
      const fresh = await refreshToken();
      if (!fresh) {
        toast("No s’ha pogut preparar el fitxer per descarregar.", "error");
        return;
      }
      triggerDownload(withDownloadFlag(fresh.url));
    } finally {
      setDownloadingFile(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 p-4">
      <span className="w-6 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
        {item.position}
      </span>
      <Thumbnail src={thumbSrc} icon="movie" className="aspect-video w-16" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-body-large text-on-surface">
          {item.title}
        </p>
        <div className="mt-0.5 flex items-center gap-3 text-label-medium text-on-surface-variant">
          {item.duration_seconds ? (
            <span className="tabular-nums">
              {formatDuration(item.duration_seconds)}
            </span>
          ) : null}
          <span>{mediaType === "audio" ? "Àudio" : "Vídeo"}</span>
          {item.status === "failed" && item.error ? (
            <span className="truncate text-error">{item.error}</span>
          ) : null}
        </div>
      </div>
      <div className="flex w-full shrink-0 items-center justify-end gap-2 sm:w-auto">
        <StatusChip status={item.status} />
        {ready ? (
          <>
            <IconButton
              variant="tonal"
              label="Reprodueix"
              onClick={onPreview}
            >
              <Icon name="play_arrow" className="text-[20px]" />
            </IconButton>
            <IconButton
              variant="tonal"
              label="Descarrega el fitxer"
              onClick={() => void handleFileDownload()}
              disabled={downloadingFile}
            >
              {downloadingFile ? (
                <Spinner className="text-[20px]" />
              ) : (
                <Icon name="download" className="text-[20px]" />
              )}
            </IconButton>
          </>
        ) : item.status === "downloading" || busy ? (
          <span className="px-2">
            <Spinner />
          </span>
        ) : item.source_url ? (
          <Button variant="outlined" size="sm" onClick={onDownload}>
            <Icon
              name={item.status === "failed" ? "refresh" : "download"}
              className="text-[18px]"
            />
            {item.status === "failed"
              ? "Torna-ho a provar"
              : item.status === "cancelled"
                ? "Torna a descarregar"
                : "Descarrega"}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
