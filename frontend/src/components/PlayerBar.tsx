import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Thumbnail from "./Thumbnail";
import PlayerSlider, { formatClock } from "./PlayerSlider";
import NowPlayingPanel from "./NowPlayingPanel";
import { usePlayer } from "../player/PlayerProvider";

/**
 * Persistent playback bar for songs. Docked above the compact navigation bar
 * and inside the content column on wider windows, so it never covers the
 * rail/drawer.
 *
 * The artwork is the expansion trigger for the full-screen song view. Videos do
 * not use this surface at all: `VideoSurface` replaces the docked bar while a
 * video is current, which also keeps clips out of the Spotify-style bar.
 */
export default function PlayerBar() {
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
    togglePlay,
    next,
    previous,
    seek,
    setVolume,
    close,
  } = usePlayer();

  const [expanded, setExpanded] = useState(false);
  const artworkButtonRef = useRef<HTMLButtonElement>(null);
  const wasExpandedRef = useRef(false);

  const hasTrack = current !== null;
  const isVideo = mediaKind === "video";
  const hasNext = hasTrack && index < queue.length - 1;
  const seekable = hasTrack && duration > 0;
  const trackId = current?.id ?? null;

  const toggleExpanded = useCallback(() => {
    setExpanded((value) => !value);
  }, []);

  // The docked bar only exists for songs. Leaving a video (manually or through
  // auto-advance) restores the bar minimized, never as a leftover fullscreen
  // song view from an earlier session.
  useEffect(() => {
    if (!trackId || isVideo) setExpanded(false);
  }, [isVideo, trackId]);

  // Returning from the full-screen song view puts focus back on its trigger.
  useEffect(() => {
    const wasExpanded = wasExpandedRef.current;
    wasExpandedRef.current = expanded;
    if (!wasExpanded || expanded || !hasTrack) return;
    const frame = window.requestAnimationFrame(() => {
      artworkButtonRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [expanded, hasTrack]);

  const credit = current
    ? [current.artist, current.album]
        .map((value) => value.trim())
        .filter((value) => value.length > 0)
        .join(" · ") || "Artista desconegut"
    : "Tria una cançó per començar a escoltar";
  const art = current?.cover_url ?? artworkUrl;

  const controls = (
    <>
      <IconButton
        label="Cançó anterior"
        onClick={previous}
        disabled={!hasTrack}
      >
        <Icon name="skip_previous" className="text-[22px]" />
      </IconButton>
      <IconButton
        variant="filled"
        size="md"
        label={isPlaying ? "Pausa" : "Reprodueix"}
        onClick={togglePlay}
        disabled={!hasTrack}
      >
        <Icon
          name={isPlaying ? "pause" : "play_arrow"}
          filled
          className="text-[24px]"
        />
      </IconButton>
      <IconButton label="Cançó següent" onClick={next} disabled={!hasNext}>
        <Icon name="skip_next" className="text-[22px]" />
      </IconButton>
    </>
  );

  const seekRow = (
    <>
      <span className="w-12 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
        {formatClock(hasTrack ? position : 0)}
      </span>
      <PlayerSlider
        label="Posició de reproducció"
        value={hasTrack ? position : 0}
        max={seekable ? duration : 0}
        disabled={!seekable}
        valueText={`${formatClock(hasTrack ? position : 0)} de ${formatClock(
          seekable ? duration : 0,
        )}`}
        onChange={seek}
      />
      <span className="w-12 shrink-0 text-label-medium tabular-nums text-on-surface-variant">
        {formatClock(seekable ? duration : 0)}
      </span>
    </>
  );

  const artworkLabel = expanded
    ? "Minimitza el reproductor"
    : "Obre el reproductor a pantalla completa";

  // Videos own the screen through VideoSurface; the audio bar is fully gone.
  if (isVideo) return null;

  return (
    <section
      aria-label="Reproductor"
      className="shrink-0 border-t border-outline-variant bg-surface-container-high"
    >
      <NowPlayingPanel expanded={expanded} onToggle={toggleExpanded} />

      <div className="flex items-center gap-3 px-3 py-2 sm:px-4">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:w-56 sm:flex-none lg:w-64">
          <button
            ref={artworkButtonRef}
            type="button"
            onClick={toggleExpanded}
            disabled={!hasTrack}
            aria-label={artworkLabel}
            aria-expanded={expanded}
            aria-controls="now-playing-panel"
            title={artworkLabel}
            className="shrink-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface-container-high disabled:cursor-default"
          >
            <Thumbnail
              src={hasTrack ? art : null}
              icon="music_note"
              className={`h-12 w-12 ${hasTrack ? "" : "opacity-60"}`}
            />
          </button>
          <button
            type="button"
            onClick={toggleExpanded}
            disabled={!hasTrack}
            aria-label="Obre el reproductor a pantalla completa"
            aria-expanded={expanded}
            aria-controls="now-playing-panel"
            title="Obre el reproductor a pantalla completa"
            className="min-w-0 flex-1 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface-container-high disabled:cursor-default"
          >
            <span
              className={`block truncate text-title-small ${
                hasTrack ? "text-on-surface" : "text-on-surface-variant"
              }`}
            >
              {hasTrack ? current.title : "No s’està reproduint res"}
            </span>
            <span className="mt-0.5 block truncate text-body-small text-on-surface-variant">
              {credit}
            </span>
          </button>
        </div>

        <div className="flex shrink-0 items-center gap-1 sm:hidden">
          {controls}
        </div>

        <div className="hidden min-w-0 flex-1 flex-col gap-1 sm:flex">
          <div className="flex items-center justify-center gap-1">
            {controls}
          </div>
          <div className="flex min-w-0 items-center gap-2">{seekRow}</div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <div className="hidden items-center gap-1 md:flex">
            <Icon
              name={volume === 0 ? "volume_off" : "volume_up"}
              className="text-[20px] text-on-surface-variant"
            />
            <div className="w-24">
              <PlayerSlider
                label="Volum"
                value={volume}
                max={1}
                step={0.01}
                valueText={`${Math.round(volume * 100)}%`}
                onChange={setVolume}
              />
            </div>
            <IconButton
              label="Tanca el reproductor"
              onClick={close}
              disabled={!hasTrack}
            >
              <Icon name="close" className="text-[20px]" />
            </IconButton>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 px-3 pb-2 sm:hidden">
        {seekRow}
      </div>
    </section>
  );
}
