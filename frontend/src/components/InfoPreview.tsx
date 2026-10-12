import { useState } from "react";
import { Clock, Film, ListVideo, Music, User } from "lucide-react";
import type { FormatName, InfoResult, OperationType } from "../types";
import { formatDuration } from "../lib";
import Thumbnail from "./Thumbnail";
import Button from "./Button";

interface InfoPreviewProps {
  info: InfoResult;
  submitting: boolean;
  onDownload: (opts: {
    operation_type: OperationType;
    format: FormatName;
    embed_subs: boolean;
  }) => void;
}

interface FormatOption {
  value: FormatName;
  label: string;
  hint: string;
  icon: typeof Film;
}

const formats: FormatOption[] = [
  { value: "best", label: "Best quality", hint: "Highest available", icon: Film },
  { value: "720p", label: "720p", hint: "≤ 720p", icon: Film },
  { value: "mp3", label: "MP3 audio", hint: "Audio only", icon: Music },
];

export default function InfoPreview({
  info,
  submitting,
  onDownload,
}: InfoPreviewProps) {
  const [format, setFormat] = useState<FormatName>("best");
  const [embedSubs, setEmbedSubs] = useState(false);

  const isPlaylist = info.type === "playlist";
  const operationType: OperationType = isPlaylist ? "playlist" : "video";
  const no720 = !isPlaylist && info.formats && !info.formats.has_720p;
  const mp3 = format === "mp3";

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-col gap-5 p-5 sm:flex-row">
        <Thumbnail
          src={info.thumbnail}
          className="aspect-video w-full rounded-lg sm:w-56"
          icon={<ListVideo className="h-6 w-6" />}
        />

        <div className="min-w-0 flex-1">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-brand/15 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-brand-hover">
            {isPlaylist ? "Playlist" : "Video"}
          </span>
          <h2 className="mt-2 text-lg font-semibold leading-snug text-fg">
            {info.title}
          </h2>

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-fg-secondary">
            {info.channel ? (
              <span className="inline-flex items-center gap-1.5">
                <User className="h-3.5 w-3.5" />
                {info.channel}
              </span>
            ) : null}
            {!isPlaylist && info.duration ? (
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" />
                {formatDuration(info.duration)}
              </span>
            ) : null}
            {isPlaylist && info.video_count ? (
              <span className="inline-flex items-center gap-1.5">
                <ListVideo className="h-3.5 w-3.5" />
                {info.video_count} videos
              </span>
            ) : null}
          </div>

          <div className="mt-5">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-muted">
              Format
            </p>
            <div className="flex flex-wrap gap-2">
              {formats.map((opt) => {
                const disabled = opt.value === "720p" && no720;
                const selected = format === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    disabled={disabled}
                    onClick={() => setFormat(opt.value)}
                    className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/70 disabled:cursor-not-allowed disabled:opacity-40 ${
                      selected
                        ? "border-brand bg-brand/15 text-brand-hover"
                        : "border-line bg-surface-2 text-fg-secondary hover:text-fg"
                    }`}
                    title={
                      disabled
                        ? "This quality is not available for this video"
                        : opt.hint
                    }
                  >
                    <opt.icon className="h-4 w-4" />
                    {opt.label}
                  </button>
                );
              })}
            </div>
            {no720 ? (
              <p className="mt-2 text-xs text-fg-muted">
                720p is not available for this video; the “Best quality” option
                will be used instead.
              </p>
            ) : null}
          </div>

          <label className="mt-4 flex cursor-pointer items-center gap-2 text-sm text-fg-secondary">
            <input
              type="checkbox"
              checked={embedSubs}
              disabled={mp3}
              onChange={(e) => setEmbedSubs(e.target.checked)}
              className="h-4 w-4 rounded border-line bg-surface-2 text-brand accent-brand"
            />
            Embed subtitles when available
            {mp3 ? (
              <span className="text-xs text-fg-muted">(video formats only)</span>
            ) : null}
          </label>

          <div className="mt-5">
            <Button
              onClick={() =>
                onDownload({ operation_type: operationType, format, embed_subs: embedSubs && !mp3 })
              }
              disabled={submitting}
            >
              {submitting
                ? "Starting…"
                : isPlaylist
                  ? "Download playlist"
                  : "Download video"}
            </Button>
          </div>
        </div>
      </div>

      {isPlaylist && info.entries && info.entries.length > 0 ? (
        <div className="max-h-72 overflow-y-auto border-t border-line">
          <ul className="divide-y divide-line/60">
            {info.entries.map((entry, i) => (
              <li key={entry.id ?? i} className="flex items-center gap-3 px-5 py-2.5">
                <span className="w-6 shrink-0 text-right text-xs tabular-nums text-fg-muted">
                  {i + 1}
                </span>
                <Thumbnail
                  src={entry.thumbnail}
                  className="h-9 w-16 rounded"
                  icon={<ListVideo className="h-4 w-4" />}
                />
                <span className="min-w-0 flex-1 truncate text-sm text-fg">
                  {entry.title}
                </span>
                {entry.duration ? (
                  <span className="shrink-0 text-xs tabular-nums text-fg-muted">
                    {formatDuration(entry.duration)}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
