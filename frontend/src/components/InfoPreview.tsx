import { useState } from "react";
import type { FormatName, InfoResult, OperationType } from "../types";
import { formatDuration } from "../lib";
import Thumbnail from "./Thumbnail";
import Button from "./Button";
import Card from "./Card";
import Icon from "./Icon";
import SegmentedButton from "./SegmentedButton";
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

const formats = [
  { value: "best" as FormatName, label: "Millor", icon: "high_quality" },
  { value: "720p" as FormatName, label: "720p", icon: "hd" },
  { value: "mp3" as FormatName, label: "MP3", icon: "music_note" },
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

  const formatOptions = formats.map((option) => ({
    ...option,
    disabled: option.value === "720p" && Boolean(no720),
  }));

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
            <SegmentedButton
              options={formatOptions}
              value={format}
              onChange={(value) => setFormat(value as FormatName)}
              label="Format de descàrrega"
            />
            {no720 ? (
              <p className="mt-2 text-body-small text-on-surface-variant">
                El 720p no està disponible per a aquest vídeo; s’utilitzarà
                l’opció «Millor».
              </p>
            ) : null}
          </div>

          <div className="mt-5">
            <Switch
              checked={embedSubs && !mp3}
              onChange={setEmbedSubs}
              disabled={mp3}
              label="Incrusta els subtítols si estan disponibles"
            />
          </div>

          <div className="mt-6">
            <Button
              onClick={() =>
                onDownload({
                  operation_type: operationType,
                  format,
                  embed_subs: embedSubs && !mp3,
                })
              }
              disabled={submitting}
            >
              <Icon name="download" className="text-[18px]" />
              {submitting
                ? "S’està iniciant…"
                : isPlaylist
                  ? "Descarrega la llista de reproducció"
                  : "Descarrega el vídeo"}
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
