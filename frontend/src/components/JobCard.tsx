import { useState } from "react";
import type { DownloadJob } from "../types/v2";
import { isActiveJob } from "../types/v2";
import { formatBytes, formatEta, formatSpeed } from "../lib";
import Card from "./Card";
import StatusChip from "./StatusChip";
import ProgressBar from "./ProgressBar";
import Spinner from "./Spinner";
import Icon from "./Icon";
import Button from "./Button";

interface JobCardProps {
  job: DownloadJob;
  /** Omit to render the card without a cancel affordance. */
  onCancel?: (jobId: string) => void | Promise<void>;
}

const indeterminateStatuses = new Set(["queued", "resolving"]);

/** Human label for the job's stored yt-dlp selector. */
function formatLabel(job: DownloadJob): string {
  const selector = job.format_selector.toLowerCase();
  if (selector.includes("bestaudio") || selector.endsWith("mp3")) {
    return "Àudio";
  }
  if (selector.includes("720")) return "Vídeo · 720p";
  return "Vídeo · Millor qualitat";
}

/** Material 3 card for one v2 download job. */
export default function JobCard({ job, onCancel }: JobCardProps) {
  const [cancelling, setCancelling] = useState(false);
  const active = isActiveJob(job.status);
  const isPlaylist = job.kind !== "video";
  const itemCount = job.item_count || (isPlaylist ? 0 : 1);
  const showItemProgress = isPlaylist && itemCount > 1;
  const waiting =
    indeterminateStatuses.has(job.status) && job.progress === 0;
  const progressStatus = job.status === "ready" ? "completed" : job.status;
  const title = job.title || "Descàrrega sense títol";

  const handleCancel = async () => {
    if (!onCancel || cancelling) return;
    setCancelling(true);
    try {
      await onCancel(job.id);
    } finally {
      setCancelling(false);
    }
  };

  return (
    <Card variant="outlined" className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-title-small text-on-surface">{title}</p>
          <p className="mt-0.5 text-body-small text-on-surface-variant">
            {isPlaylist ? "Llista de reproducció" : "Vídeo"}
            {" · "}
            {formatLabel(job)}
            {isPlaylist && itemCount > 0 ? ` · ${itemCount} vídeos` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusChip status={job.status} />
          {active && onCancel ? (
            <Button
              variant="text"
              size="sm"
              onClick={handleCancel}
              disabled={cancelling}
              aria-label={`Cancel·la la descàrrega de ${title}`}
            >
              {cancelling ? (
                <Spinner className="text-[18px]" />
              ) : (
                <Icon name="cancel" className="text-[18px]" />
              )}
              <span className="hidden sm:inline">
                {cancelling ? "Cancel·lant…" : "Cancel·la"}
              </span>
            </Button>
          ) : null}
        </div>
      </div>

      {showItemProgress && active ? (
        <p className="mt-2 text-body-small text-on-surface-variant">
          {`Vídeo ${Math.max(job.item_index, 1)} de ${itemCount}`}
          {job.current_item_title ? ` — ${job.current_item_title}` : ""}
        </p>
      ) : null}

      <div className="mt-3">
        <ProgressBar
          value={job.progress}
          status={progressStatus}
          indeterminate={waiting}
          label={`Progrés de la descàrrega de ${title}`}
        />
      </div>

      {showItemProgress &&
      job.status === "downloading" &&
      job.current_item_progress > 0 ? (
        <div className="mt-2">
          <ProgressBar
            value={job.current_item_progress}
            label={`Progrés del vídeo ${Math.max(job.item_index, 1)}`}
          />
        </div>
      ) : null}

      {job.status === "downloading" ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-label-medium text-on-surface-variant">
          <span className="tabular-nums">{job.progress.toFixed(0)}%</span>
          <span className="tabular-nums">
            {formatBytes(job.downloaded_bytes)}
            {job.total_bytes ? ` / ${formatBytes(job.total_bytes)}` : ""}
          </span>
          {job.speed > 0 ? (
            <span className="tabular-nums">{formatSpeed(job.speed)}</span>
          ) : null}
          {job.eta_seconds != null && job.eta_seconds > 0 ? (
            <span className="tabular-nums">
              {formatEta(job.eta_seconds)} restants
            </span>
          ) : null}
        </div>
      ) : null}

      {job.error ? (
        <p
          role="alert"
          className="mt-2 line-clamp-3 text-body-small text-error"
        >
          {job.error}
        </p>
      ) : null}
    </Card>
  );
}
