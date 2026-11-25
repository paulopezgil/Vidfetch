import { useEffect, useLayoutEffect, useRef } from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Thumbnail from "./Thumbnail";
import PlayerSlider, { formatClock } from "./PlayerSlider";
import { usePlayer } from "../player/PlayerProvider";

interface NowPlayingPanelProps {
  /** Whether the full-screen player is open. */
  expanded: boolean;
  /** Toggle the full-screen player; the docked bar stays usable when closed. */
  onToggle: () => void;
}

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Full-screen now-playing surface.
 *
 * Audio shows the large artwork and track metadata. Video mounts the provider's
 * single `<video>` element, so the real video fills the screen while playback
 * state and source management stay in the player provider. The panel remains
 * mounted while collapsed (hidden), keeping the video element attached so
 * minimizing never interrupts playback.
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

  const panelRef = useRef<HTMLDivElement | null>(null);
  const minimizeRef = useRef<HTMLButtonElement | null>(null);
  const videoHostRef = useRef<HTMLDivElement | null>(null);
  const onToggleRef = useRef(onToggle);

  useEffect(() => {
    onToggleRef.current = onToggle;
  }, [onToggle]);

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

  // Modal focus management: focus the minimize control on open, close on
  // Escape, keep Tab inside the full-screen surface, and restore the previous
  // focus when it closes.
  useEffect(() => {
    if (!expanded) return;
    const previous = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      minimizeRef.current?.focus();
    });

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onToggleRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
      ).filter((element) => !element.hasAttribute("disabled"));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (!panelRef.current?.contains(active)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      if (previous?.isConnected) previous.focus?.();
    };
  }, [expanded]);

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
        <Icon name="skip_previous" className="text-[24px]" />
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
          className="text-[26px]"
        />
      </IconButton>
      <IconButton label="Pista següent" onClick={next} disabled={!hasNext}>
        <Icon name="skip_next" className="text-[24px]" />
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

  const volumeRow = (
    <>
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
    </>
  );

  const metadata = (
    <div className="min-w-0 text-center lg:text-left">
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
      ref={panelRef}
      id="now-playing-panel"
      role={expanded ? "dialog" : undefined}
      aria-modal={expanded ? true : undefined}
      aria-label="Ara sonant"
      aria-hidden={!expanded}
      className={
        expanded
          ? "fixed inset-0 z-[80] flex flex-col overflow-hidden bg-surface text-on-surface"
          : "hidden"
      }
    >
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-outline-variant px-4 py-3 sm:px-6">
        <div className="min-w-0">
          <p className="text-label-medium text-on-surface-variant">
            Ara sonant
          </p>
          <p className="truncate text-title-medium text-on-surface">
            {current.title}
          </p>
        </div>
        <IconButton
          buttonRef={minimizeRef}
          label="Minimitza el reproductor"
          title="Minimitza el reproductor"
          onClick={onToggle}
        >
          <Icon name="expand_more" className="text-[24px]" />
        </IconButton>
      </header>

      {isVideo ? (
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black">
            <div
              ref={videoHostRef}
              className="h-full w-full [&>video]:h-full [&>video]:w-full [&>video]:object-contain"
            />
          </div>

          <aside className="shrink-0 space-y-4 overflow-y-auto border-t border-outline-variant bg-surface-container p-4 sm:p-5 lg:w-96 lg:border-l lg:border-t-0">
            {metadata}
            <div className="flex items-center justify-center gap-1 lg:justify-start">
              {transportControls}
            </div>
            <div className="flex items-center gap-2">{seekRow}</div>
            <div className="flex items-center gap-2">{volumeRow}</div>
          </aside>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-6 overflow-y-auto px-4 py-6 sm:px-6">
          <Thumbnail
            src={cover}
            icon="music_note"
            className="h-56 w-56 sm:h-72 sm:w-72 lg:h-80 lg:w-80"
          />
          <div className="w-full max-w-xl space-y-4 text-center">
            {metadata}
            <div className="flex items-center gap-2">{seekRow}</div>
            <div className="flex items-center justify-center gap-1">
              {transportControls}
            </div>
            <div className="mx-auto flex max-w-xs items-center gap-2">
              {volumeRow}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
