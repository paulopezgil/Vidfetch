import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";
import PlayerSlider, { formatClock } from "./PlayerSlider";
import { usePlayer } from "../player/PlayerProvider";

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Dedicated video playback surface.
 *
 * It replaces the docked audio bar whenever a video is current: the provider's
 * single `<video>` element is mounted in a 16:9 stage, with metadata and custom
 * transport controls. The surface opens as a centered overlay and can be
 * maximized to a fixed, viewport-filling screen. Both states use the same DOM
 * node, so maximizing never re-creates the element or restarts playback.
 */
export default function VideoSurface() {
  const {
    current,
    queue,
    index,
    isPlaying,
    position,
    duration,
    mediaKind,
    videoElement,
    togglePlay,
    next,
    previous,
    seek,
    close,
  } = usePlayer();

  const [maximized, setMaximized] = useState(false);
  const panelRef = useRef<HTMLElement | null>(null);
  const videoHostRef = useRef<HTMLDivElement | null>(null);
  const maximizeRef = useRef<HTMLButtonElement | null>(null);
  const playRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const wasVideoRef = useRef(false);

  const isVideo = mediaKind === "video" && current !== null;

  // Moving to a song (or stopping) dismisses the maximized state so the screen
  // is back to normal whenever the next video starts.
  useEffect(() => {
    if (!isVideo) setMaximized(false);
  }, [isVideo]);

  // The surface takes over the app when a clip starts, so keyboard focus moves
  // to its play control and returns to the page afterwards.
  useEffect(() => {
    if (isVideo && !wasVideoRef.current) {
      wasVideoRef.current = true;
      returnFocusRef.current = document.activeElement as HTMLElement | null;
      const frame = window.requestAnimationFrame(() => {
        playRef.current?.focus();
      });
      return () => window.cancelAnimationFrame(frame);
    }
    if (!isVideo && wasVideoRef.current) {
      wasVideoRef.current = false;
      const previous = returnFocusRef.current;
      if (previous?.isConnected) previous.focus?.();
    }
  }, [isVideo]);

  // The provider owns the element. Appending it here keeps a single source of
  // truth across song/video and maximized/minimized transitions.
  useLayoutEffect(() => {
    const host = videoHostRef.current;
    if (!host || !videoElement) return;
    if (videoElement.parentNode !== host) host.appendChild(videoElement);
    return () => {
      if (videoElement.parentNode === host) host.removeChild(videoElement);
    };
  }, [videoElement, isVideo]);

  // The screen is modal in both states: Escape minimizes (or closes when
  // centered) and Tab stays inside the surface.
  useEffect(() => {
    if (!isVideo) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (maximized) {
          setMaximized(false);
        } else {
          close();
        }
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
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [close, isVideo, maximized]);

  // Maximizing focuses the control that can restore the centered screen.
  useEffect(() => {
    if (!maximized) return;
    const previous = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      maximizeRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
      if (previous?.isConnected) previous.focus?.();
    };
  }, [maximized]);

  if (!current || mediaKind !== "video") return null;

  const artist = current.artist?.trim();
  const album = current.album?.trim();
  const credit = [artist, album].filter(Boolean).join(" · ");
  const seekable = duration > 0;
  const hasNext = index < queue.length - 1;
  const timeText = `${formatClock(position)} de ${formatClock(
    seekable ? duration : 0,
  )}`;

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

  return (
    <div
      className={
        maximized
          ? "fixed inset-0 z-[75] flex bg-surface text-on-surface"
          : "fixed inset-0 z-[75] flex items-center justify-center bg-scrim/32 p-2 sm:p-4"
      }
    >
      <section
        ref={panelRef}
        role="dialog"
        aria-modal={true}
        aria-label="Reproductor de vídeo"
        className={
          maximized
            ? "flex h-full w-full flex-col overflow-hidden bg-surface text-on-surface"
            : "flex max-h-[calc(100dvh-1rem)] w-full max-w-5xl flex-col overflow-y-auto rounded-xl bg-surface-container text-on-surface shadow-elevation-3 sm:max-h-[calc(100dvh-2rem)]"
        }
      >
        <header className="flex shrink-0 items-start gap-2 border-b border-outline-variant px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-label-medium text-on-surface-variant">Vídeo</p>
            <h2 className="truncate text-title-medium text-on-surface">
              {current.title}
            </h2>
            {credit ? (
              <p className="truncate text-body-small text-on-surface-variant">
                {credit}
              </p>
            ) : null}
          </div>
          <IconButton
            buttonRef={maximizeRef}
            label={maximized ? "Minimitza" : "Maximitza"}
            title={maximized ? "Minimitza" : "Maximitza"}
            onClick={() => setMaximized((value) => !value)}
            ariaPressed={maximized}
          >
            <Icon
              name={maximized ? "fullscreen_exit" : "fullscreen"}
              className="text-[22px]"
            />
          </IconButton>
          <IconButton label="Tanca el vídeo" onClick={close}>
            <Icon name="close" className="text-[22px]" />
          </IconButton>
        </header>

        <div
          className={
            maximized
              ? "relative min-h-0 flex-1 bg-video-stage"
              : "relative aspect-video w-full shrink-0 bg-video-stage"
          }
        >
          <div
            ref={videoHostRef}
            className="absolute inset-0 [&>video]:h-full [&>video]:w-full [&>video]:object-contain"
          />
        </div>

        <div className="shrink-0 space-y-2 border-t border-outline-variant bg-surface-container px-4 py-3">
          <div className="flex items-center gap-2">{seekRow}</div>
          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
            <p className="truncate text-body-small tabular-nums text-on-surface-variant">
              {queue.length > 0 ? `${index + 1} / ${queue.length}` : ""}
            </p>
            <div className="flex items-center justify-center gap-1">
              <IconButton label="Pista anterior" onClick={previous}>
                <Icon name="skip_previous" className="text-[24px]" />
              </IconButton>
              <IconButton
                buttonRef={playRef}
                variant="filled"
                size="md"
                label={isPlaying ? "Pausa" : "Reprodueix"}
                onClick={togglePlay}
              >
                <Icon
                  name={isPlaying ? "pause" : "play_arrow"}
                  filled
                  className="text-[26px]"
                />
              </IconButton>
              <IconButton
                label="Pista següent"
                onClick={next}
                disabled={!hasNext}
              >
                <Icon name="skip_next" className="text-[24px]" />
              </IconButton>
            </div>
            <span aria-hidden="true" />
          </div>
        </div>
      </section>
    </div>
  );
}
