import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { FormatName, PlaylistDetail, PlaylistItem } from "../types";
import { formatBytes, formatDuration } from "../lib";
import {
  fileUrl,
  getPlaylist,
  rebuildZip,
  startDownload,
  streamTask,
} from "../api";
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
import { useToast } from "../components/Toast";

const formatOptions = [
  { value: "best", label: "Millor", icon: "high_quality" },
  { value: "720p", label: "720p", icon: "hd" },
  { value: "mp3", label: "MP3", icon: "music_note" },
];

export default function PlaylistDetail() {
  const { id = "" } = useParams();
  const toast = useToast();
  const [detail, setDetail] = useState<PlaylistDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [format, setFormat] = useState<FormatName>("best");
  const [embedSubs, setEmbedSubs] = useState(false);
  const [active, setActive] = useState(false);
  const [buildingZip, setBuildingZip] = useState(false);
  const [busyUrl, setBusyUrl] = useState<string | null>(null);

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
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!active) return;
    const interval = window.setInterval(refresh, 3000);
    return () => window.clearInterval(interval);
  }, [active, refresh]);

  const startTask = useCallback(
    async (payload: Parameters<typeof startDownload>[0], url: string | null) => {
      try {
        const { task_id } = await startDownload(payload);
        setActive(true);
        setBusyUrl(url);
        toast("Descàrrega iniciada", "info");
        streamTask(
          task_id,
          () => {},
          () => {
            setActive(false);
            setBusyUrl(null);
            refresh();
          },
        );
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "No s’ha pogut iniciar la descàrrega",
          "error",
        );
      }
    },
    [refresh, toast],
  );

  async function handleRebuildZip() {
    setBuildingZip(true);
    try {
      const result = await rebuildZip(id, true);
      toast(result.built ? "ZIP creat" : "El ZIP ja està actualitzat", "success");
      refresh();
    } catch (e) {
      toast(
        e instanceof Error ? e.message : "No s’ha pogut crear el ZIP",
        "error",
      );
    } finally {
      setBuildingZip(false);
    }
  }

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
          to="/library"
          className="mb-4 inline-flex items-center gap-1.5 text-label-large text-primary hover:text-primary/80"
        >
          <Icon name="arrow_back" className="text-[20px]" /> Biblioteca
        </Link>
        <EmptyState
          icon="playlist_remove"
          title="No s’ha trobat la llista de reproducció"
          description={error ?? "Aquesta llista de reproducció no existeix."}
        />
      </div>
    );
  }

  const total = detail.item_count || 1;
  const overall = Math.round((detail.downloaded_count / total) * 100);
  const hasZip = Boolean(detail.zip_path);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <Link
        to="/library"
        className="inline-flex w-fit items-center gap-1.5 rounded-full pr-3 text-label-large text-primary hover:text-primary/80"
      >
        <Icon name="arrow_back" className="text-[20px]" /> Biblioteca
      </Link>

      <Card variant="outlined" className="p-4 sm:p-6">
        <div className="flex flex-col gap-5 sm:flex-row">
          <Thumbnail
            src={detail.thumbnail_url}
            icon="playlist_play"
            className="aspect-video w-full sm:w-52"
          />
          <div className="min-w-0 flex-1">
            <h1 className="text-headline-small text-on-surface">
              {detail.title}
            </h1>
            <p className="mt-1 text-body-medium text-on-surface-variant">
              {detail.channel}
              {detail.channel ? " · " : ""}
              {detail.item_count} vídeos
              {detail.total_size ? ` · ${formatBytes(detail.total_size)}` : ""}
            </p>

            <div className="mt-4">
              <div className="mb-1.5 flex items-center justify-between text-label-medium text-on-surface-variant">
                <span>
                  {detail.downloaded_count} de {detail.item_count} descarregats
                  {detail.failed_count
                    ? ` · ${detail.failed_count} fallits`
                    : ""}
                </span>
                <span className="tabular-nums">{overall}%</span>
              </div>
              <ProgressBar
                value={overall}
                label="Progrés de la descàrrega de la llista"
                status={
                  detail.failed_count && detail.downloaded_count
                    ? "completed"
                    : undefined
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
                onChange={(value) => setFormat(value as FormatName)}
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
              <Button
                onClick={() =>
                  startTask(
                    {
                      url: detail.url,
                      operation_type: "playlist",
                      format,
                      embed_subs: embedSubs && format !== "mp3",
                      playlist_id: detail.playlist_id,
                    },
                    null,
                  )
                }
              >
                <Icon name="download" className="text-[18px]" /> Descarrega la
                llista de reproducció
              </Button>
              {hasZip ? (
                <a
                  href={fileUrl(detail.zip_path)}
                  className="inline-flex h-10 items-center gap-2 rounded-full bg-secondary-container px-6 text-label-large text-on-secondary-container transition-colors hover:bg-secondary-container/90"
                >
                  <Icon name="folder_zip" className="text-[18px]" /> Descarrega el
                  ZIP
                </a>
              ) : detail.downloaded_count > 0 ? (
                <Button
                  variant="tonal"
                  onClick={handleRebuildZip}
                  disabled={buildingZip}
                >
                  {buildingZip ? (
                    <Spinner />
                  ) : (
                    <Icon name="folder_zip" className="text-[18px]" />
                  )}
                  Crea el ZIP
                </Button>
              ) : null}
              {hasZip ? (
                <Button
                  variant="text"
                  size="sm"
                  onClick={handleRebuildZip}
                  disabled={buildingZip}
                >
                  <Icon name="refresh" className="text-[18px]" /> Reconstrueix
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      </Card>

      {detail.items.length > 0 ? (
        <Card
          variant="outlined"
          className="divide-y divide-outline-variant overflow-hidden"
        >
          {detail.items.map((item) => (
            <ItemRow
              key={item.index}
              item={item}
              busy={busyUrl === item.url}
              onDownload={() =>
                startTask(
                  {
                    url: item.url,
                    operation_type: "playlist_item",
                    format,
                    embed_subs: embedSubs && format !== "mp3",
                    playlist_id: detail.playlist_id,
                  },
                  item.url,
                )
              }
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
    </div>
  );
}

function ItemRow({
  item,
  busy,
  onDownload,
}: {
  item: PlaylistItem;
  busy: boolean;
  onDownload: () => void;
}) {
  const thumbSrc = item.video_id ? `/api/thumb/${item.video_id}.jpg` : null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 p-4">
      <span className="w-6 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
        {item.index + 1}
      </span>
      <Thumbnail src={thumbSrc} icon="movie" className="aspect-video w-16" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-body-large text-on-surface">
          {item.title}
        </p>
        <div className="mt-0.5 flex items-center gap-3 text-label-medium text-on-surface-variant">
          {item.duration ? (
            <span className="tabular-nums">{formatDuration(item.duration)}</span>
          ) : null}
          {item.size ? <span>{formatBytes(item.size)}</span> : null}
          {item.status === "failed" && item.error ? (
            <span className="truncate text-error">{item.error}</span>
          ) : null}
        </div>
      </div>
      <div className="flex w-full shrink-0 items-center justify-end gap-2 sm:w-auto">
        <StatusChip status={item.status} />
        {item.status === "downloaded" && item.filename ? (
          <IconButton
            href={fileUrl(item.filename)}
            variant="tonal"
            label="Descarrega el fitxer"
          >
            <Icon name="download" className="text-[20px]" />
          </IconButton>
        ) : item.status === "downloading" || busy ? (
          <span className="px-2">
            <Spinner />
          </span>
        ) : (
          <Button variant="outlined" size="sm" onClick={onDownload}>
            <Icon
              name={item.status === "failed" ? "refresh" : "download"}
              className="text-[18px]"
            />
            {item.status === "failed"
              ? "Torna-ho a provar"
              : item.status === "missing"
                ? "Torna a descarregar"
                : "Descarrega"}
          </Button>
        )}
      </div>
    </div>
  );
}
