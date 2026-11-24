import { useLayoutEffect, useRef } from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Thumbnail from "./Thumbnail";
import PlayerSlider, { formatClock } from "./PlayerSlider";
import { usePlayer } from "../player/PlayerProvider";

interface NowPlayingPanelProps {
  /** Whether the panel is visible above the docked player bar. */
  expanded: boolean;
  /** Collapse the panel; the bar stays docked and usable. */
  onToggle: () => void;
}

/**
 * Expandable now-playing surface above the persistent player bar.
 *
 * Audio shows the large artwork and track metadata. Video mounts the provider's
 * single `<video>` element, so the real video is visible while it plays and the
 * same transport controls remain available when the panel is collapsed in the
 * bar below.
 */
export default function NowPlayingPanel({
  expanded,
  onToggle,
}: NowPlayingPanelProps) {
  const {
    current,
    queue,
    index,
    isPlaying,
    position,
    duration,
    artworkUrl,
    volume,
    mediaKind,
    videoElement,
    togglePlay,
    next,
    previous,
    seek,
    setVolume,
  } = usePlayer();

  const videoHostRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const host = videoHostRef.current;
    if (!host || !videoElement) return;
    host.appendChild(videoElement);
    return () => {
      if (videoElement.parentNode === host) {
        host.removeChild(videoElement);
      }
    };
  }, [videoElement, mediaKind]);

  if (!current) return null;

  const isVideo = mediaKind === "video";
  const cover = current.cover_url ?? artworkUrl;
  const artist = current.artist?.trim() || "Artista desconegut";
  const album = current.album?.trim();
  const seekable = duration > 0;
  const hasNext = index < queue.length - 1;
  const timeText = `${formatClock(position)} de ${formatClock(
    seekable ? duration : 0,
  )}`;

  const transportControls = (
    <>
      <IconButton
        label="Pista anterior"
        onClick={previous}
        disabled={!current}
      >
        <Icon name="skip_previous" className="text-[22px]" />
      </IconButton>
      <IconButton
        variant="filled"
        size="md"
        label={isPlaying ? "Pausa" : "Reprodueix"}
        onClick={togglePlay}
        disabled={!current}
      >
        <Icon
          name={isPlaying ? "pause" : "play_arrow"}
          filled
          className="text-[24px]"
        />
      </IconButton>
      <IconButton label="Pista següent" onClick={next} disabled={!hasNext}>
        <Icon name="skip_next" className="text-[22px]" />
      </IconButton>
    </>
  );

  const seekRow = (
    <>
      <span className="w-12 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
        {formatClock(position)}
      </span>
      <PlayerSlider
        label="Posició de reproducció"
        value={position}
        max={seekable ? duration : 0}
        disabled={!seekable}
        valueText={timeText}
        onChange={seek}
      />
      <span className="w-12 shrink-0 text-label-medium tabular-nums text-on-surface-variant">
        {formatClock(seekable ? duration : 0)}
      </span>
    </>
  );

  const metadata = (
    <div className="min-w-0 text-center sm:text-left">
      <p className="truncate text-title-large text-on-surface">
        {current.title}
      </p>
      <p className="truncate text-body-medium text-on-surface-variant">
        {artist}
      </p>
      {album ? (
        <p className="truncate text-body-small text-on-surface-variant">
          {album}
        </p>
      ) : null}
    </div>
  );

  return (
    <div
      id="now-playing-panel"
      className={expanded ? "block" : "hidden"}
      aria-hidden={!expanded}
    >
      <section
        aria-label="Ara sonant"
        className="border-b border-outline-variant bg-surface-container"
      >
        <div className="mx-auto w-full max-w-5xl px-4 py-4 sm:px-6">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-label-large text-on-surface-variant">
              Ara sonant
            </h2>
            <IconButton label="Amaga el reproductor" onClick={onToggle}>
              <Icon name="expand_more" className="text-[22px]" />
            </IconButton>
          </div>

          {isVideo ? (
            <div className="flex flex-col gap-4 md:flex-row md:items-center">
              <div className="relative mx-auto w-full max-w-2xl overflow-hidden rounded-lg bg-black md:mx-0 md:flex-1">
                <div
                  ref={videoHostRef}
                  className="aspect-video w-full [&>video]:h-full [&>video]:w-full [&>video]:object-contain"
                />
              </div>
              <div className="w-full min-w-0 space-y-3 md:w-80 lg:w-96">
                {metadata}
                <div className="flex items-center justify-center gap-1 md:justify-start">
                  {transportControls}
                </div>
                <div className="flex items-center gap-2">{seekRow}</div>
                <div className="flex items-center gap-2">
                  <Icon
                    name={volume === 0 ? "volume_off" : "volume_up"}
                    className="text-[20px] text-on-surface-variant"
                  />
                  <div className="min-w-0 flex-1">
                    <PlayerSlider
                      label="Volum"
                      value={volume}
                      max={1}
                      step={0.01}
                      valueText={`${Math.round(volume * 100)}%`}
                      onChange={setVolume}
                    />
                  </div>
                  <span className="w-10 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
                    {Math.round(volume * 100)}%
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-5 sm:flex-row">
              <Thumbnail
                src={cover}
                icon="music_note"
                className="h-32 w-32 sm:h-40 sm:w-40"
              />
              <div className="min-w-0 flex-1 space-y-3">
                {metadata}
                <div className="flex items-center gap-2">{seekRow}</div>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
