import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Download,
  Film,
  ListVideo,
  Music,
  RefreshCw,
  Package,
  RotateCw,
} from "lucide-react";
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
import Spinner from "../components/Spinner";
import EmptyState from "../components/EmptyState";
import { useToast } from "../components/Toast";

const formats: { value: FormatName; label: string; icon: typeof Film }[] = [
  { value: "best", label: "Best", icon: Film },
  { value: "720p", label: "720p", icon: Film },
  { value: "mp3", label: "MP3", icon: Music },
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
      setError(e instanceof Error ? e.message : "Failed to load playlist.");
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
        toast("Download started", "info");
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
        toast(e instanceof Error ? e.message : "Failed to start download", "error");
      }
    },
    [refresh, toast],
  );

  async function handleRebuildZip() {
    setBuildingZip(true);
    try {
      const result = await rebuildZip(id, true);
      toast(result.built ? "ZIP created" : "ZIP is up to date", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to build ZIP", "error");
    } finally {
      setBuildingZip(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-fg-secondary">
        <Spinner className="mr-2" /> Loading playlist…
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        <Link to="/library" className="mb-4 inline-flex items-center gap-1.5 text-sm text-fg-secondary hover:text-fg">
          <ArrowLeft className="h-4 w-4" /> Back to library
        </Link>
        <EmptyState
          icon={<ListVideo className="h-6 w-6" />}
          title="Playlist not found"
          description={error ?? "This playlist does not exist."}
        />
      </div>
    );
  }

  const total = detail.item_count || 1;
  const overall = Math.round((detail.downloaded_count / total) * 100);
  const hasZip = Boolean(detail.zip_path);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-4 py-6 sm:px-6">
      <Link
        to="/library"
        className="inline-flex items-center gap-1.5 text-sm text-fg-secondary transition-colors hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" /> Library
      </Link>

      <div className="card p-5">
        <div className="flex flex-col gap-5 sm:flex-row">
          <Thumbnail
            src={detail.thumbnail_url}
            className="aspect-video w-full rounded-lg sm:w-52"
            icon={<ListVideo className="h-6 w-6" />}
          />
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold leading-snug text-fg">
              {detail.title}
            </h1>
            <p className="mt-1 text-sm text-fg-secondary">
              {detail.channel}
              {detail.channel ? " · " : ""}
              {detail.item_count} videos
              {detail.total_size ? ` · ${formatBytes(detail.total_size)}` : ""}
            </p>

            <div className="mt-4">
              <div className="mb-1 flex items-center justify-between text-xs text-fg-secondary">
                <span>
                  {detail.downloaded_count} of {detail.item_count} downloaded
                  {detail.failed_count ? ` · ${detail.failed_count} failed` : ""}
                </span>
                <span className="tabular-nums">{overall}%</span>
              </div>
              <ProgressBar
                value={overall}
                label="Playlist download progress"
                status={
                  detail.failed_count && detail.downloaded_count
                    ? "completed"
                    : undefined
                }
              />
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2">
              {formats.map((f) => {
                const selected = format === f.value;
                return (
                  <button
                    key={f.value}
                    onClick={() => setFormat(f.value)}
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/70 ${
                      selected
                        ? "border-brand bg-brand/15 text-brand-hover"
                        : "border-line bg-surface-2 text-fg-secondary hover:text-fg"
                    }`}
                  >
                    <f.icon className="h-4 w-4" /> {f.label}
                  </button>
                );
              })}
              <label className="ml-1 flex cursor-pointer items-center gap-2 text-sm text-fg-secondary">
                <input
                  type="checkbox"
                  checked={embedSubs}
                  onChange={(e) => setEmbedSubs(e.target.checked)}
                  className="h-4 w-4 rounded accent-brand"
                />
                Embed subtitles
              </label>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2">
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
                <Download className="h-4 w-4" /> Download playlist
              </Button>
              {hasZip ? (
                <a
                  href={fileUrl(detail.zip_path)}
                  className="inline-flex h-10 items-center gap-2 rounded-lg border border-line bg-surface-2 px-4 text-sm font-medium text-fg transition-colors hover:bg-line/60"
                >
                  <Package className="h-4 w-4" /> Download ZIP
                </a>
              ) : detail.downloaded_count > 0 ? (
                <Button variant="secondary" onClick={handleRebuildZip} disabled={buildingZip}>
                  {buildingZip ? <Spinner /> : <Package className="h-4 w-4" />}
                  Create ZIP
                </Button>
              ) : null}
              {hasZip ? (
                <Button variant="ghost" size="sm" onClick={handleRebuildZip} disabled={buildingZip}>
                  <RefreshCw className="h-4 w-4" /> Rebuild
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {detail.items.length > 0 ? (
        <div className="card divide-y divide-line/60">
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
        </div>
      ) : (
        <EmptyState
          icon={<ListVideo className="h-6 w-6" />}
          title="No items to show"
          description="This playlist does not have any downloadable items yet."
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
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
      <span className="w-6 shrink-0 text-right text-xs tabular-nums text-fg-muted">
        {item.index + 1}
      </span>
      <Thumbnail
        src={thumbSrc}
        className="aspect-video w-16 rounded-md"
        icon={<Film className="h-4 w-4" />}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-fg">{item.title}</p>
        <div className="mt-0.5 flex items-center gap-3 text-xs text-fg-muted">
          {item.duration ? (
            <span className="tabular-nums">{formatDuration(item.duration)}</span>
          ) : null}
          {item.size ? <span>{formatBytes(item.size)}</span> : null}
          {item.status === "failed" && item.error ? (
            <span className="truncate text-danger">{item.error}</span>
          ) : null}
        </div>
      </div>
      <div className="flex w-full shrink-0 items-center justify-end gap-2 sm:w-auto">
        <StatusChip status={item.status} />
        {item.status === "downloaded" && item.filename ? (
          <IconButton href={fileUrl(item.filename)} label="Download file">
            <Download className="h-4 w-4" />
          </IconButton>
        ) : item.status === "downloading" || busy ? (
          <Spinner />
        ) : item.status === "failed" ? (
          <button
            onClick={onDownload}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2.5 text-[13px] font-medium text-fg transition-colors hover:bg-line/60"
          >
            <RotateCw className="h-4 w-4" /> Retry
          </button>
        ) : (
          <button
            onClick={onDownload}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2.5 text-[13px] font-medium text-fg transition-colors hover:bg-line/60"
          >
            <Download className="h-4 w-4" />
            {item.status === "missing" ? "Re-download" : "Download"}
          </button>
        )}
      </div>
    </div>
  );
}
