import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";
import PlayerSlider, { formatClock } from "./PlayerSlider";
import { usePlayer } from "../player/PlayerProvider";

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Safari exposes the Fullscreen API behind `webkit`-prefixed members. */
interface WebkitDocument extends Document {
  webkitFullscreenElement?: Element | null;
  webkitCurrentFullScreenElement?: Element | null;
  webkitExitFullscreen?: () => void;
}

/** iOS Safari only supports fullscreen through the video-specific API. */
interface WebkitVideoElement extends HTMLVideoElement {
  webkitRequestFullscreen?: () => void;
  webkitEnterFullscreen?: () => void;
  webkitExitFullscreen?: () => void;
  webkitDisplayingFullscreen?: boolean;
}

/** The document's current fullscreen element, including Safari prefixes. */
function fullscreenElement(): Element | null {
  const doc = document as WebkitDocument;
  return (
    doc.fullscreenElement ??
    doc.webkitFullscreenElement ??
    doc.webkitCurrentFullScreenElement ??
    null
  );
}

/** Whether the provider's video is the element being shown fullscreen. */
function isVideoFullscreen(video: HTMLVideoElement | null): boolean {
  if (!video) return false;
  const element = video as WebkitVideoElement;
  return (
    fullscreenElement() === video ||
    element.webkitDisplayingFullscreen === true
  );
}

/** Leave native fullscreen through whichever API the browser implements. */
function leaveNativeFullscreen(video: HTMLVideoElement | null): void {
  const doc = document as WebkitDocument;
  try {
    if (fullscreenElement() !== null) {
      // `exitFullscreen` rejects when the document is not in fullscreen.
      const result =
        typeof doc.exitFullscreen === "function"
          ? doc.exitFullscreen()
          : doc.webkitExitFullscreen?.();
      void Promise.resolve(result).catch(() => {});
      return;
    }

    // iOS Safari reports fullscreen on the video itself, not on the document.
    const element = video as WebkitVideoElement | null;
    if (element?.webkitDisplayingFullscreen) {
      element.webkitExitFullscreen?.();
    }
  } catch {
    // Best effort: the browser may have left fullscreen already.
  }
}

/**
 * Dedicated video playback surface.
 *
 * It replaces the docked audio bar whenever a video is current: the provider's
 * single `<video>` element is mounted in a 16:9 stage, with metadata and custom
 * transport controls. The surface opens as a centered overlay and can enter
 * the browser's native fullscreen on the video element, where only the video
 * (with the browser's own auto-hiding controls) is shown. If the Fullscreen API
 * is unavailable or refuses the request, the previous fixed, viewport-filling
 * CSS layout is used as a fallback. Native fullscreen never re-creates the
 * element, so playback and the current time are preserved.
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

  const [nativeFullscreen, setNativeFullscreen] = useState(false);
  const [fallbackMaximized, setFallbackMaximized] = useState(false);
  const panelRef = useRef<HTMLElement | null>(null);
  const videoHostRef = useRef<HTMLDivElement | null>(null);
  const maximizeRef = useRef<HTMLButtonElement | null>(null);
  const playRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const wasVideoRef = useRef(false);
  const nativeRef = useRef(false);
  const wasNativeRef = useRef(false);
  /** Set when the browser leaves fullscreen, so that same Escape does not close. */
  const justExitedNativeRef = useRef(0);

  const isVideo = mediaKind === "video" && current !== null;
  const maximized = nativeFullscreen || fallbackMaximized;

  /** Mirror native state in a ref so key handlers never act on stale state. */
  const syncNativeState = useCallback((active: boolean) => {
    if (nativeRef.current && !active) {
      justExitedNativeRef.current = Date.now();
    }
    nativeRef.current = active;
    setNativeFullscreen(active);
    if (active) setFallbackMaximized(false);
  }, []);

  const exitNativeFullscreen = useCallback(() => {
    leaveNativeFullscreen(videoElement);
  }, [videoElement]);

  const enterNativeFullscreen = useCallback(async (): Promise<boolean> => {
    const video = videoElement as WebkitVideoElement | null;
    if (!video) return false;

    // Try each API in turn: standard, desktop Safari's prefix, then the
    // iPhone-only video API. A rejection moves on to the next one.
    const attempts: Array<() => Promise<void> | void> = [];
    if (typeof video.requestFullscreen === "function") {
      attempts.push(() =>
        video.requestFullscreen({ navigationUI: "hide" }),
      );
    }
    if (typeof video.webkitRequestFullscreen === "function") {
      attempts.push(() => video.webkitRequestFullscreen?.());
    }
    if (typeof video.webkitEnterFullscreen === "function") {
      attempts.push(() => video.webkitEnterFullscreen?.());
    }

    for (const attempt of attempts) {
      try {
        await Promise.resolve(attempt());
        return true;
      } catch {
        // The browser refused this API; the next one may still work.
      }
    }
    return false;
  }, [videoElement]);

  // Native fullscreen state is driven by the browser's own events, so Escape
  // and the browser UI keep the button and layout in sync.
  useEffect(() => {
    const video = videoElement as WebkitVideoElement | null;
    if (!video) return;
    const doc = document as WebkitDocument;

    const sync = () => syncNativeState(isVideoFullscreen(video));
    const onBegin = () => syncNativeState(true);
    const onEnd = () => syncNativeState(false);

    doc.addEventListener("fullscreenchange", sync);
    doc.addEventListener("webkitfullscreenchange", sync);
    video.addEventListener("webkitbeginfullscreen", onBegin);
    video.addEventListener("webkitendfullscreen", onEnd);
    sync();

    return () => {
      doc.removeEventListener("fullscreenchange", sync);
      doc.removeEventListener("webkitfullscreenchange", sync);
      video.removeEventListener("webkitbeginfullscreen", onBegin);
      video.removeEventListener("webkitendfullscreen", onEnd);
      // Never leave the document (or an iOS video) stuck in fullscreen.
      if (isVideoFullscreen(video)) {
        leaveNativeFullscreen(video);
      }
    };
  }, [syncNativeState, videoElement]);

  // The browser native controls are available only in native fullscreen; they
  // auto-hide and provide pause, seek and an explicit exit.
  useEffect(() => {
    if (!videoElement) return;
    if (!nativeFullscreen) {
      videoElement.controls = false;
      return;
    }
    videoElement.controls = true;
    return () => {
      videoElement.controls = false;
    };
  }, [nativeFullscreen, videoElement]);

  // Moving to a song (or closing) dismisses native fullscreen and any CSS
  // fallback so the screen is normal whenever the next video starts.
  useEffect(() => {
    if (isVideo) return;
    setFallbackMaximized(false);
    if (isVideoFullscreen(videoElement)) leaveNativeFullscreen(videoElement);
    syncNativeState(false);
  }, [isVideo, syncNativeState, videoElement]);

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

  // The screen is modal in both states: Escape minimizes native/CSS fullscreen
  // (or closes when centered) and Tab stays inside the surface.
  useEffect(() => {
    if (!isVideo) return;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        if (isVideoFullscreen(videoElement) || nativeRef.current) {
          // Let the browser's own Escape handling run, but make sure the
          // document leaves fullscreen instead of closing the surface.
          leaveNativeFullscreen(videoElement);
          return;
        }
        // Some browsers deliver the Escape that exits fullscreen to the page
        // right after `fullscreenchange`; that key must not close the video.
        if (Date.now() - justExitedNativeRef.current < 250) return;
        event.preventDefault();
        if (fallbackMaximized) {
          setFallbackMaximized(false);
        } else {
          close();
        }
        return;
      }
      if (event.key !== "Tab" || nativeRef.current) return;

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
  }, [close, fallbackMaximized, isVideo, videoElement]);

  // The CSS fallback focuses the control that can restore the centered screen.
  useEffect(() => {
    if (!fallbackMaximized) return;
    const previous = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      maximizeRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
      if (previous?.isConnected) previous.focus?.();
    };
  }, [fallbackMaximized]);

  // Leaving native fullscreen (Escape or the browser UI) restores focus to the
  // maximize control once the custom chrome is visible again.
  useEffect(() => {
    if (nativeFullscreen) {
      wasNativeRef.current = true;
      return;
    }
    if (!wasNativeRef.current) return;
    wasNativeRef.current = false;
    const frame = window.requestAnimationFrame(() => {
      maximizeRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [nativeFullscreen]);

  if (!current || mediaKind !== "video") return null;

  const artist = current.artist?.trim();
  const album = current.album?.trim();
  const credit = [artist, album].filter(Boolean).join(" · ");
  const seekable = duration > 0;
  const hasNext = index < queue.length - 1;
  const timeText = `${formatClock(position)} de ${formatClock(
    seekable ? duration : 0,
  )}`;

  function toggleFullscreen() {
    if (isVideoFullscreen(videoElement)) {
      exitNativeFullscreen();
      return;
    }
    if (fallbackMaximized) {
      setFallbackMaximized(false);
      return;
    }
    void enterNativeFullscreen().then((entered) => {
      // The Fullscreen API is unavailable or refused the request: keep a
      // working, viewport-filling CSS layout instead.
      if (!entered) setFallbackMaximized(true);
    });
  }

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
        fallbackMaximized
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
          fallbackMaximized
            ? "flex h-full w-full flex-col overflow-hidden bg-surface text-on-surface"
            : "flex max-h-[calc(100dvh-1rem)] w-full max-w-5xl flex-col overflow-y-auto rounded-xl bg-surface-container text-on-surface shadow-elevation-3 sm:max-h-[calc(100dvh-2rem)]"
        }
      >
        <header
          className={
            nativeFullscreen
              ? "hidden"
              : "flex shrink-0 items-start gap-2 border-b border-outline-variant px-4 py-3"
          }
        >
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
            onClick={toggleFullscreen}
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
            fallbackMaximized
              ? "relative min-h-0 flex-1 bg-video-stage"
              : "relative aspect-video w-full shrink-0 bg-video-stage"
          }
        >
          <div
            ref={videoHostRef}
            className="absolute inset-0 [&>video]:h-full [&>video]:w-full [&>video]:object-contain"
          />
        </div>

        <div
          className={
            nativeFullscreen
              ? "hidden"
              : "shrink-0 space-y-2 border-t border-outline-variant bg-surface-container px-4 py-3"
          }
        >
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
