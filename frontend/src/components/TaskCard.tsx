import type { Task } from "../types";
import { formatBytes, formatEta, formatSpeed, isTerminal } from "../lib";
import ProgressBar from "./ProgressBar";
import StatusChip from "./StatusChip";
import Thumbnail from "./Thumbnail";
import IconButton from "./IconButton";
import Card from "./Card";
import Icon from "./Icon";

interface TaskCardProps {
  task: Task;
  onCancel: (taskId: string) => void;
}

const formatLabels: Record<string, string> = {
  best: "MP4 · Millor",
  "720p": "MP4 · 720p",
  mp3: "Àudio MP3",
};

const indeterminateStatuses = new Set([
  "queued",
  "fetching information",
  "processing",
]);

export default function TaskCard({ task, onCancel }: TaskCardProps) {
  const isPlaylist = task.operation_type === "playlist";
  const done = isTerminal(task.status);

  const thumbSrc = task.playlist_id
    ? `/api/thumb/playlist_${task.playlist_id}.jpg`
    : task.video_id
      ? `/api/thumb/${task.video_id}.jpg`
      : null;

  const thumbIcon =
    task.format === "mp3"
      ? "music_note"
      : isPlaylist
        ? "playlist_play"
        : "movie";
  const indeterminate =
    indeterminateStatuses.has(task.status) && task.progress === 0;

  return (
    <Card variant="outlined" className="p-4">
      <div className="flex items-start gap-3">
        <Thumbnail src={thumbSrc} icon={thumbIcon} className="aspect-video w-24" />

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-title-small text-on-surface">
                {task.title || "S’està preparant…"}
              </p>
              <p className="mt-0.5 text-body-small text-on-surface-variant">
                {formatLabels[task.format] ?? task.format}
                {isPlaylist ? " · Llista de reproducció" : ""}
                {isPlaylist && task.item_count
                  ? ` · ${task.completed_items} de ${task.item_count}`
                  : ""}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <StatusChip status={task.status} />
              {!done ? (
                <IconButton
                  variant="danger"
                  label="Cancel·la"
                  onClick={() => onCancel(task.task_id)}
                >
                  <Icon name="close" className="text-[20px]" />
                </IconButton>
              ) : null}
            </div>
          </div>

          {isPlaylist && task.item_count > 1 ? (
            <p className="mt-2 text-body-small text-on-surface-variant">
              Vídeo {task.item_index} de {task.item_count}
              {task.current_item_title ? ` — ${task.current_item_title}` : ""}
            </p>
          ) : null}

          <div className="mt-3">
            <ProgressBar
              value={task.progress}
              label="Progrés de la descàrrega"
              status={task.status}
              indeterminate={indeterminate}
            />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-label-medium text-on-surface-variant">
            {task.status === "downloading" ? (
              <>
                <span className="tabular-nums">
                  {task.progress.toFixed(0)}%
                </span>
                <span className="tabular-nums">
                  {formatBytes(task.downloaded_bytes)}
                  {task.total_bytes
                    ? ` / ${formatBytes(task.total_bytes)}`
                    : ""}
                </span>
                {task.speed > 0 ? (
                  <span className="tabular-nums">{formatSpeed(task.speed)}</span>
                ) : null}
                {task.eta > 0 ? (
                  <span className="tabular-nums">
                    {formatEta(task.eta)} restants
                  </span>
                ) : null}
              </>
            ) : null}
            {isPlaylist && task.item_count > 1 ? (
              <span className="tabular-nums">
                Total {task.progress.toFixed(0)}%
              </span>
            ) : null}
            {task.error && !done ? (
              <span className="text-error">{task.error}</span>
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}
