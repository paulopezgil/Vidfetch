import { useState } from "react";
import type { FormatName, InfoResult, OperationType } from "../types";
import { formatDuration } from "../lib";
import { isAudioFormat } from "../lib/formats";
import Thumbnail from "./Thumbnail";
import Button from "./Button";
import Card from "./Card";
import Icon from "./Icon";
import FormatMenu from "./FormatMenu";
import Switch from "./Switch";

interface InfoPreviewProps {
  info: InfoResult;
  submitting: boolean;
  onDownload: (opts: {
    operation_type: OperationType;
    format: FormatName;
    embed_subs: boolean;
  }) => void;
}

export default function InfoPreview({
  info,
  submitting,
  onDownload,
}: InfoPreviewProps) {
  const [format, setFormat] = useState<FormatName>("best");
  const [embedSubs, setEmbedSubs] = useState(false);

  const isPlaylist = info.type === "playlist";
  const operationType: OperationType = isPlaylist ? "playlist" : "video";
  // Audio profiles never carry subtitles, so embedding is turned off.
  const audioOnly = isAudioFormat(format);

  return (
    <Card variant="outlined" className="overflow-hidden">
      <div className="flex flex-col gap-5 p-4 sm:flex-row sm:p-6">
        <Thumbnail
          src={info.thumbnail}
          icon="movie"
          className="aspect-video w-full sm:w-56"
        />

        <div className="min-w-0 flex-1">
          <span className="inline-flex items-center gap-1 rounded-sm bg-surface-container-highest px-2 py-0.5 text-label-medium text-on-surface-variant">
            <Icon
              name={isPlaylist ? "playlist_play" : "movie"}
              className="text-[16px]"
            />
            {isPlaylist ? "Llista de reproducció" : "Vídeo"}
          </span>

          <h2 className="mt-3 text-title-large text-on-surface">{info.title}</h2>

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-body-medium text-on-surface-variant">
            {info.channel ? (
              <span className="inline-flex items-center gap-1.5">
                <Icon name="person" className="text-[18px]" />
                {info.channel}
              </span>
            ) : null}
            {!isPlaylist && info.duration ? (
              <span className="inline-flex items-center gap-1.5">
                <Icon name="schedule" className="text-[18px]" />
                {formatDuration(info.duration)}
              </span>
            ) : null}
            {isPlaylist && info.video_count ? (
              <span className="inline-flex items-center gap-1.5">
                <Icon name="playlist_play" className="text-[18px]" />
                {info.video_count} vídeos
              </span>
            ) : null}
          </div>

          <div className="mt-5">
            <p className="mb-2 text-label-large text-on-surface-variant">
              Format
            </p>
            <FormatMenu
              value={format}
              onChange={setFormat}
              isPlaylist={isPlaylist}
              availableHeights={info.formats?.heights ?? []}
            />
          </div>

          <div className="mt-5">
            <Switch
              checked={embedSubs && !audioOnly}
              onChange={setEmbedSubs}
              disabled={audioOnly}
              label="Incrusta els subtítols si estan disponibles"
            />
          </div>

          <div className="mt-6">
            <Button
              onClick={() =>
                onDownload({
                  operation_type: operationType,
                  format,
                  embed_subs: embedSubs && !audioOnly,
                })
              }
              disabled={submitting}
            >
              <Icon name="download" className="text-[18px]" />
              {submitting
                ? "S’està iniciant…"
                : isPlaylist
                  ? "Descarrega la llista de reproducció"
                  : "Descarrega"}
            </Button>
          </div>
        </div>
      </div>

      {isPlaylist && info.entries && info.entries.length > 0 ? (
        <div className="max-h-72 overflow-y-auto border-t border-outline-variant">
          <ul className="divide-y divide-outline-variant">
            {info.entries.map((entry, index) => (
              <li
                key={entry.id ?? index}
                className="flex items-center gap-3 px-4 py-2.5"
              >
                <span className="w-6 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
                  {index + 1}
                </span>
                <Thumbnail
                  src={entry.thumbnail}
                  icon="movie"
                  className="h-9 w-16"
                />
                <span className="min-w-0 flex-1 truncate text-body-medium text-on-surface">
                  {entry.title}
                </span>
                {entry.duration ? (
                  <span className="shrink-0 text-label-medium tabular-nums text-on-surface-variant">
                    {formatDuration(entry.duration)}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}
