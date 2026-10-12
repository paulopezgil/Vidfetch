import { ListVideo, Film, Music, X } from "lucide-react";
import type { Task } from "../types";
import { formatBytes, formatEta, formatSpeed, isTerminal } from "../lib";
import ProgressBar from "./ProgressBar";
import StatusChip from "./StatusChip";
import Thumbnail from "./Thumbnail";
import IconButton from "./IconButton";

interface TaskCardProps {
  task: Task;
  onCancel: (taskId: string) => void;
}

const formatLabels: Record<string, string> = {
  best: "MP4 · Best",
  "720p": "MP4 · 720p",
  mp3: "MP3 audio",
};

const indeterminateStatuses = new Set([
  "queued",
  "fetching information",
  "processing",
  "packaging zip",
]);

export default function TaskCard({ task, onCancel }: TaskCardProps) {
  const isPlaylist = task.operation_type === "playlist";
  const done = isTerminal(task.status);

  const thumbSrc = task.playlist_id
    ? `/api/thumb/playlist_${task.playlist_id}.jpg`
    : task.video_id
      ? `/api/thumb/${task.video_id}.jpg`
      : null;

  const icon = task.format === "mp3" ? Music : isPlaylist ? ListVideo : Film;
  const Icon = icon;
  const indeterminate = indeterminateStatuses.has(task.status) && task.progress === 0;

  return (
    <div className="card p-4">
      <div className="flex items-start gap-3">
        <Thumbnail
          src={thumbSrc}
          className="aspect-video w-24 rounded-md"
          icon={<Icon className="h-5 w-5" />}
        />

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-fg">
                {task.title || "Preparing…"}
              </p>
              <p className="mt-0.5 text-xs text-fg-secondary">
                {formatLabels[task.format] ?? task.format}
                {isPlaylist ? " · Playlist" : ""}
                {isPlaylist && task.item_count
                  ? ` · ${task.completed_items} of ${task.item_count}`
                  : ""}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <StatusChip status={task.status} />
              {!done ? (
                <IconButton label="Cancel" onClick={() => onCancel(task.task_id)}>
                  <X className="h-4 w-4" />
                </IconButton>
              ) : null}
            </div>
          </div>

          {isPlaylist && task.item_count > 1 ? (
            <p className="mt-2 text-xs text-fg-secondary">
              Downloading video {task.item_index} of {task.item_count}
              {task.current_item_title
                ? ` — ${task.current_item_title}`
                : ""}
            </p>
          ) : null}

          <div className="mt-2.5">
            <ProgressBar
              value={task.progress}
              label="Download progress"
              status={task.status}
              indeterminate={indeterminate}
            />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
            {task.status === "downloading" ? (
              <>
                <span className="tabular-nums">{task.progress.toFixed(0)}%</span>
                <span className="tabular-nums">
                  {formatBytes(task.downloaded_bytes)}
                  {task.total_bytes
                    ? ` / ${formatBytes(task.total_bytes)}`
                    : ""}
                </span>
                {task.speed > 0 ? (
                  <span className="tabular-nums">
                    {formatSpeed(task.speed)}
                  </span>
                ) : null}
                {task.eta > 0 ? (
                  <span className="tabular-nums">
                    {formatEta(task.eta)} left
                  </span>
                ) : null}
              </>
            ) : null}
            {isPlaylist && task.item_count > 1 ? (
              <span className="tabular-nums">
                Overall {task.progress.toFixed(0)}%
              </span>
            ) : null}
            {task.error && !done ? (
              <span className="text-danger">{task.error}</span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
