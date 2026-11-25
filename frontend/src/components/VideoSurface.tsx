import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { Track } from "../types/v2";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Menu from "./Menu";
import TrackEditDialog from "./TrackEditDialog";
import { useToast } from "./Toast";
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

/** Desktop Safari's legacy element API. */
interface WebkitElement extends HTMLElement {
  webkitRequestFullscreen?: () => void;
  webkitRequestFullScreen?: () => void;
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

/**
 * Whether this surface (its stage, or the video on iOS) owns native fullscreen.
 *
 * The legacy APIs can return `undefined` without doing anything, so callers
 * must verify the document state instead of trusting the call.
 */
function isStageFullscreen(
  stage: Element | null,
  video: HTMLVideoElement | null,
): boolean {
  const current = fullscreenElement();
  if (stage !== null && current === stage) return true;
  if (video !== null) {
    const element = video as WebkitVideoElement;
    return current === video || element.webkitDisplayingFullscreen === true;
  }
  return false;
}

/** Leave native fullscreen through whichever API the browser implements. */
function leaveNativeFullscreen(
  stage: Element | null,
  video: HTMLVideoElement | null,
): void {
  const doc = document as WebkitDocument;
  const element = video as WebkitVideoElement | null;
  try {
    const current = fullscreenElement();
    if (current !== null && (current === stage || current === video)) {
      // `exitFullscreen` rejects when the document is not in fullscreen.
      const result =
        typeof doc.exitFullscreen === "function"
          ? doc.exitFullscreen()
          : doc.webkitExitFullscreen?.();
      void Promise.resolve(result).catch(() => {});
      return;
    }

    // iOS Safari reports fullscreen on the video itself, not on the document.
    if (element?.webkitDisplayingFullscreen) {
      element.webkitExitFullscreen?.();
    }
  } catch {
    // Best effort: the browser may have left fullscreen already.
  }
}

/**
 * Wait until the stage (or the iOS video) really is fullscreen.
 *
 * A fulfilled `requestFullscreen()` promise is not enough: legacy prefixed
 * calls return `undefined` even when the request is ignored, and some browsers
 * resolve before the top-layer state is observable. Poll briefly and listen to
 * the fullscreen events; only returning `true` on an observed state keeps the
 * caller from skipping the CSS fallback.
 */
function waitForFullscreenEntry(
  stage: Element | null,
  video: HTMLVideoElement | null,
  timeout = 400,
): Promise<boolean> {
  if (isStageFullscreen(stage, video)) return Promise.resolve(true);
  return new Promise((resolve) => {
    const doc = document as WebkitDocument;
    const webkitVideo = video as WebkitVideoElement | null;
    const startedAt = Date.now();
    let settled = false;
    let timer: number | undefined;

    const cleanup = () => {
      doc.removeEventListener("fullscreenchange", onChange);
      doc.removeEventListener("webkitfullscreenchange", onChange);
      webkitVideo?.removeEventListener("webkitbeginfullscreen", onChange);
      if (timer !== undefined) window.clearTimeout(timer);
    };
    const finish = (entered: boolean) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(entered);
    };
    function onChange() {
      if (isStageFullscreen(stage, video)) finish(true);
    }
    function poll() {
      if (settled) return;
      if (isStageFullscreen(stage, video)) {
        finish(true);
        return;
      }
      if (Date.now() - startedAt >= timeout) {
        finish(false);
        return;
      }
      timer = window.setTimeout(poll, 30);
    }

    doc.addEventListener("fullscreenchange", onChange);
    doc.addEventListener("webkitfullscreenchange", onChange);
    webkitVideo?.addEventListener("webkitbeginfullscreen", onChange);
    poll();
  });
}

/**
 * Dedicated video playback surface.
 *
 * It replaces the docked audio bar whenever a video is current: the provider's
 * single `<video>` element is mounted in a 16:9 stage, with metadata and custom
 * transport controls. The surface opens as a centered overlay and can enter
 * the browser's native fullscreen on the stage itself, where only the video
 * (with the browser's own auto-hiding controls) is shown. If the Fullscreen API
 * is unavailable, is silently ignored, or refuses the request, the previous
 * fixed, viewport-filling CSS layout is used as a fallback. Native fullscreen
 * never re-creates the element, so playback and the current time are preserved.
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
    updateTrack,
    close,
  } = usePlayer();

  const toast = useToast();
  const [editing, setEditing] = useState<Track | null>(null);

  const [nativeFullscreen, setNativeFullscreen] = useState(false);
  const [fallbackMaximized, setFallbackMaximized] = useState(false);
  const panelRef = useRef<HTMLElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const videoHostRef = useRef<HTMLDivElement | null>(null);
  const maximizeRef = useRef<HTMLButtonElement | null>(null);
  const playRef = useRef<HTMLButtonElement | null>(null);
  /** Lets the key handler ignore Esc/Tab while the edit dialog is on top. */
  const editingRef = useRef(editing);
  editingRef.current = editing;
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const wasVideoRef = useRef(false);
  const nativeRef = useRef(false);
  const wasNativeRef = useRef(false);
  /** Set when the browser leaves fullscreen, so that same Escape does not close. */
  const justExitedNativeRef = useRef(0);

  const isVideo = mediaKind === "video" && current !== null;
  const maximized = nativeFullscreen || fallbackMaximized;

  const handleSaved = useCallback(
    (track: Track) => {
      // Metadata-only refresh: the video keeps playing from the same source.
      updateTrack(track);
      toast("Track actualitzat", "success");
    },
    [toast, updateTrack],
  );

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
    leaveNativeFullscreen(stageRef.current, videoElement);
  }, [videoElement]);

  const enterNativeFullscreen = useCallback(async (): Promise<boolean> => {
    const stage = stageRef.current;
    if (!stage) return false;
    const video = videoElement as WebkitVideoElement | null;
    const webkitStage = stage as WebkitElement;

    // Fullscreen the stage, never the raw <video>: the browser then paints
    // exactly the stage in the top layer, so the element cannot be reparented
    // or measured against the wrong box. Every legacy call is only an attempt;
    // `waitForFullscreenEntry` decides whether it actually worked.
    const attempts: Array<() => Promise<unknown> | void> = [];
    if (typeof stage.requestFullscreen === "function") {
      attempts.push(() =>
        stage.requestFullscreen({ navigationUI: "hide" }),
      );
    }
    if (typeof webkitStage.webkitRequestFullscreen === "function") {
      attempts.push(() => webkitStage.webkitRequestFullscreen?.());
    }
    if (typeof webkitStage.webkitRequestFullScreen === "function") {
      attempts.push(() => webkitStage.webkitRequestFullScreen?.());
    }
    // iOS Safari refuses element fullscreen and only supports the video API.
    if (video && typeof video.webkitEnterFullscreen === "function") {
      attempts.push(() => video.webkitEnterFullscreen?.());
    }

    for (const attempt of attempts) {
      let rejected = false;
      try {
        await Promise.resolve(attempt());
      } catch {
        // A rejection means this API definitely refused; a void legacy call
        // means nothing at all, so both are verified below.
        rejected = true;
      }
      if (isStageFullscreen(stage, video)) return true;
      if (rejected) continue;
      if (await waitForFullscreenEntry(stage, video)) return true;
    }
    return false;
  }, [videoElement]);

  // Native fullscreen state is driven by the browser's own events, so Escape
  // and the browser UI keep the button and layout in sync. The effect waits
  // until a video surface exists: at app start the provider has a video element
  // but the stage is not mounted yet.
  useEffect(() => {
    const video = videoElement as WebkitVideoElement | null;
    if (!isVideo || !video) return;
    const stage = stageRef.current;
    const doc = document as WebkitDocument;

    const sync = () => syncNativeState(isStageFullscreen(stage, video));
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
      if (isStageFullscreen(stage, video)) {
        leaveNativeFullscreen(stage, video);
      }
    };
  }, [isVideo, syncNativeState, videoElement]);

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
    if (isStageFullscreen(stageRef.current, videoElement)) {
      leaveNativeFullscreen(stageRef.current, videoElement);
    }
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
      // The edit dialog owns Escape and Tab while it is open.
      if (editingRef.current) return;
      if (event.key === "Escape") {
        if (
          isStageFullscreen(stageRef.current, videoElement) ||
          nativeRef.current
        ) {
          // Let the browser's own Escape handling run, but make sure the
          // document leaves fullscreen instead of closing the surface.
          leaveNativeFullscreen(stageRef.current, videoElement);
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
    if (
      nativeRef.current ||
      isStageFullscreen(stageRef.current, videoElement)
    ) {
      exitNativeFullscreen();
      return;
    }
    if (fallbackMaximized) {
      setFallbackMaximized(false);
      return;
    }
    void enterNativeFullscreen().then((entered) => {
      if (entered) {
        // The fullscreenchange event normally reports this too; setting it
        // here keeps the button in sync even if a browser omits the event.
        syncNativeState(true);
        return;
      }
      // The Fullscreen API is unavailable, ignored, or refused the request:
      // keep a working, viewport-filling CSS layout instead.
      setFallbackMaximized(true);
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
          <Menu
            label="Més accions"
            actions={[
              {
                id: "edit",
                label: "Edita els detalls",
                icon: "edit",
                onSelect: () => setEditing(current),
              },
            ]}
          />
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
          ref={stageRef}
          className={
            nativeFullscreen
              ? "video-stage fixed inset-0 h-screen w-screen shrink-0 overflow-hidden bg-video-stage"
              : fallbackMaximized
                ? "video-stage relative min-h-0 flex-1 overflow-hidden bg-video-stage"
                : "video-stage relative aspect-video w-full shrink-0 overflow-hidden bg-video-stage"
          }
        >
          <div
            ref={videoHostRef}
            className="absolute inset-0 [&>video]:absolute [&>video]:inset-0 [&>video]:h-full [&>video]:w-full [&>video]:object-contain"
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

      <TrackEditDialog
        open={editing !== null}
        track={editing}
        onClose={() => setEditing(null)}
        onSaved={handleSaved}
      />
    </div>
  );
}
