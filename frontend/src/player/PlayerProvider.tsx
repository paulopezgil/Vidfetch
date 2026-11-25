import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { MediaToken, Track } from "../types/v2";
import { getMediaToken } from "../lib/api";
import { mediaTypeFor } from "../lib/trackDisplay";
import { getOfflineMediaBlob } from "../offline/media";

/** Media surface the current track needs: a detached audio or video element. */
export type MediaKind = "audio" | "video";

export interface PlayerContextValue {
  /** Track loaded in the bar, or `null` when the player is idle. */
  current: Track | null;
  /** Tracks the current item can advance through. */
  queue: Track[];
  /** Position of `current` inside `queue`. */
  index: number;
  isPlaying: boolean;
  position: number;
  duration: number;
  /** Signed thumbnail for the current track, when the API provides one. */
  artworkUrl: string | null;
  /** Playback volume between 0 and 1. */
  volume: number;
  /** Whether the current source is audio or video. */
  mediaKind: MediaKind | null;
  /**
   * Provider-owned video element. The now-playing surface mounts it while the
   * current track is a video, so playback survives expanding/collapsing the
   * panel and never creates a second competing element.
   */
  videoElement: HTMLVideoElement | null;
  /**
   * Load `track` and start playing. When `queue` is provided it becomes the
   * play order (the current item is located by id, or prepended if absent).
   */
  playTrack: (track: Track, queue?: Track[]) => void;
  togglePlay: () => void;
  next: () => void;
  previous: () => void;
  seek: (seconds: number) => void;
  setVolume: (volume: number) => void;
  /** Stop playback and return the bar to its idle state. */
  close: () => void;
}

const PlayerContext = createContext<PlayerContextValue | null>(null);

/** Audio playback uses the detached audio element; everything else is video. */
function mediaKindFor(track: Track): MediaKind {
  return mediaTypeFor(track) === "audio" ? "audio" : "video";
}

/** Token lifetime in epoch milliseconds, tolerant of a malformed payload. */
function tokenExpiry(token: MediaToken): number {
  const parsed = Date.parse(token.expires_at);
  if (Number.isFinite(parsed)) return parsed;
  const seconds = Number(token.expires_in);
  if (Number.isFinite(seconds) && seconds > 0) {
    return Date.now() + seconds * 1000;
  }
  return Date.now() + 60_000;
}

/** Refresh a token slightly before the server-side expiry. */
function isExpired(expiresAt: number): boolean {
  return expiresAt === 0 || Date.now() >= expiresAt - 5_000;
}

/** `media.play()` rejects on autoplay policy or a replaced source. */
function attemptPlay(media: HTMLMediaElement): void {
  const result = media.play();
  if (result && typeof result.catch === "function") {
    result.catch(() => {
      // The bar simply stays paused; the user can retry.
    });
  }
}

/**
 * Persistent player shared by every route in the app shell.
 *
 * The provider owns an audio element and a video element, choosing the one that
 * matches the current track. The video element is mounted by the now-playing
 * panel, so a real video surface is shown while the bar stays docked.
 *
 * Playback state, the queue with auto-advance, and the short-lived signed URL
 * refresh all live here. Token or network failures never throw into the UI: the
 * bar stays visible and paused.
 */
export function PlayerProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<Track | null>(null);
  const [queue, setQueue] = useState<Track[]>([]);
  const [index, setIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolumeState] = useState(1);
  const [artworkUrl, setArtworkUrl] = useState<string | null>(null);
  const [mediaKind, setMediaKind] = useState<MediaKind | null>(null);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(
    null,
  );

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  /** Element currently carrying the source; events from the other are ignored. */
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const currentRef = useRef<Track | null>(null);
  const playingRef = useRef(false);
  const queueRef = useRef<Track[]>([]);
  const indexRef = useRef(0);
  const volumeRef = useRef(1);
  const expiresAtRef = useRef(0);
  const loadIdRef = useRef(0);
  const retryRef = useRef(0);
  /** Object URL of the current local copy, revoked on every source change. */
  const blobUrlRef = useRef<string | null>(null);

  const endedRef = useRef<() => void>(() => {});
  const errorRef = useRef<() => void>(() => {});
  const canPlayRef = useRef<() => void>(() => {});

  const setPlaying = useCallback((value: boolean) => {
    playingRef.current = value;
    setIsPlaying(value);
  }, []);

  const getAudio = useCallback((): HTMLAudioElement => {
    if (audioRef.current) return audioRef.current;
    const audio = new Audio();
    audio.preload = "auto";
    audio.volume = volumeRef.current;
    audioRef.current = audio;
    return audio;
  }, []);

  const getVideo = useCallback((): HTMLVideoElement => {
    if (videoRef.current) return videoRef.current;
    const video = document.createElement("video");
    video.preload = "auto";
    video.playsInline = true;
    video.setAttribute("playsinline", "");
    video.volume = volumeRef.current;
    videoRef.current = video;
    return video;
  }, []);

  const applyQueue = useCallback((nextQueue: Track[], nextIndex: number) => {
    queueRef.current = nextQueue;
    indexRef.current = nextIndex;
    setQueue(nextQueue);
    setIndex(nextIndex);
  }, []);

  /** Revoke the object URL of the previous local copy, if any. */
  const releaseBlobUrl = useCallback(() => {
    if (!blobUrlRef.current) return;
    URL.revokeObjectURL(blobUrlRef.current);
    blobUrlRef.current = null;
  }, []);

  /** Stop both elements and drop the active source before loading a new one. */
  const resetMedia = useCallback(() => {
    mediaRef.current = null;
    const audio = audioRef.current;
    const video = videoRef.current;
    audio?.pause();
    video?.pause();
    audio?.removeAttribute("src");
    video?.removeAttribute("src");
    audio?.load();
    video?.load();
    releaseBlobUrl();
    expiresAtRef.current = 0;
  }, [releaseBlobUrl]);

  /** Load a signed source for `track`, optionally resuming mid-track. */
  const loadSource = useCallback(
    async (track: Track, autoplay: boolean, resumeAt = 0) => {
      const audio = getAudio();
      const video = getVideo();
      const kind = mediaKindFor(track);
      const media = kind === "video" ? video : audio;

      const loadId = ++loadIdRef.current;
      const startAt =
        Number.isFinite(resumeAt) && resumeAt > 0 ? resumeAt : 0;

      // Stop whatever was loaded before, so a failed token request can never
      // leave the previous track playing behind a paused bar.
      resetMedia();

      currentRef.current = track;
      setCurrent(track);
      setArtworkUrl(null);
      setDuration(track.duration_seconds ?? 0);
      setPosition(startAt);
      setPlaying(false);
      setMediaKind(kind);

      const applyStartOffset = () => {
        if (startAt <= 0) return;
        const onMetadata = () => {
          media.removeEventListener("loadedmetadata", onMetadata);
          if (loadId !== loadIdRef.current) return;
          try {
            media.currentTime = startAt;
          } catch {
            // Seeking before the media is ready is not fatal.
          }
        };
        media.addEventListener("loadedmetadata", onMetadata);
      };

      try {
        // Prefer the local copy: it plays offline and needs no token. Songs and
        // videos both use the same cache; automatic transfers remain audio-only,
        // while a manually saved video is read here just like a song.
        const local = await getOfflineMediaBlob(track.asset_id);
        if (loadId !== loadIdRef.current) return;

        if (local) {
          const objectUrl = URL.createObjectURL(local);
          blobUrlRef.current = objectUrl;
          // A blob URL never expires, so do not refresh it on play.
          expiresAtRef.current = Number.MAX_SAFE_INTEGER;
          setArtworkUrl(track.cover_url ?? null);
          mediaRef.current = media;
          media.src = objectUrl;
          media.load();
          applyStartOffset();
          if (autoplay) attemptPlay(media);
          return;
        }

        const token = await getMediaToken(track.asset_id);
        if (loadId !== loadIdRef.current) return;

        expiresAtRef.current = tokenExpiry(token);
        setArtworkUrl(track.cover_url ?? token.thumbnail_url ?? null);
        mediaRef.current = media;
        media.src = token.url;
        media.load();
        applyStartOffset();

        if (autoplay) attemptPlay(media);
      } catch {
        if (loadId !== loadIdRef.current) return;
        // The signed URL could not be minted. Keep the track in the bar, but
        // paused and silent; nothing is surfaced to the user.
        mediaRef.current = null;
        media.removeAttribute("src");
        releaseBlobUrl();
        expiresAtRef.current = 0;
        setPlaying(false);
      }
    },
    [getAudio, getVideo, releaseBlobUrl, resetMedia, setPlaying],
  );

  const seek = useCallback((seconds: number) => {
    const media = mediaRef.current;
    if (!media) return;
    const max =
      Number.isFinite(media.duration) && media.duration > 0
        ? media.duration
        : currentRef.current?.duration_seconds ?? 0;
    const next = Math.max(0, max > 0 ? Math.min(seconds, max) : seconds);
    try {
      media.currentTime = next;
    } catch {
      return;
    }
    setPosition(next);
  }, []);

  const advance = useCallback(
    (autoplay: boolean) => {
      const currentQueue = queueRef.current;
      if (currentQueue.length === 0) return;

      const nextIndex = indexRef.current + 1;
      if (nextIndex >= currentQueue.length) {
        // End of the queue: stop on the last item instead of looping.
        const media = mediaRef.current;
        if (media) {
          media.pause();
          setPosition(
            Number.isFinite(media.duration) && media.duration > 0
              ? media.duration
              : currentRef.current?.duration_seconds ?? 0,
          );
        }
        setPlaying(false);
        return;
      }

      retryRef.current = 0;
      applyQueue(currentQueue, nextIndex);
      void loadSource(currentQueue[nextIndex], autoplay);
    },
    [applyQueue, loadSource, setPlaying],
  );

  const next = useCallback(() => {
    advance(playingRef.current);
  }, [advance]);

  const previous = useCallback(() => {
    const media = mediaRef.current;
    if (!media) return;
    // Like most players: restart the current item unless we are near its start.
    if (media.currentTime > 3 || indexRef.current === 0) {
      seek(0);
      return;
    }
    const previousIndex = Math.max(0, indexRef.current - 1);
    retryRef.current = 0;
    applyQueue(queueRef.current, previousIndex);
    void loadSource(queueRef.current[previousIndex], playingRef.current);
  }, [applyQueue, loadSource, seek]);

  const togglePlay = useCallback(() => {
    const media = mediaRef.current;
    const track = currentRef.current;
    if (!media || !track) return;
    if (!media.paused) {
      media.pause();
      return;
    }
    if (!media.src || isExpired(expiresAtRef.current)) {
      void loadSource(track, true, media.ended ? 0 : media.currentTime || 0);
      return;
    }
    if (media.ended) seek(0);
    attemptPlay(media);
  }, [loadSource, seek]);

  const playTrack = useCallback(
    (track: Track, nextQueue?: Track[]) => {
      let resolvedQueue: Track[];
      let nextIndex: number;
      if (nextQueue && nextQueue.length > 0) {
        const found = nextQueue.findIndex((item) => item.id === track.id);
        if (found >= 0) {
          resolvedQueue = nextQueue;
          nextIndex = found;
        } else {
          resolvedQueue = [track, ...nextQueue];
          nextIndex = 0;
        }
      } else {
        resolvedQueue = [track];
        nextIndex = 0;
      }
      applyQueue(resolvedQueue, nextIndex);

      // Choosing the active track toggles it instead of restarting playback.
      if (currentRef.current?.id === track.id) {
        const media = mediaRef.current;
        if (!media) {
          retryRef.current = 0;
          void loadSource(track, true, 0);
          return;
        }
        if (!media.paused) {
          media.pause();
          return;
        }
        retryRef.current = 0;
        if (!media.src || isExpired(expiresAtRef.current)) {
          void loadSource(
            track,
            true,
            media.ended ? 0 : media.currentTime || 0,
          );
          return;
        }
        if (media.ended) seek(0);
        attemptPlay(media);
        return;
      }

      retryRef.current = 0;
      void loadSource(track, true, 0);
    },
    [applyQueue, loadSource, seek],
  );

  const setVolume = useCallback((value: number) => {
    const nextVolume = Math.max(0, Math.min(1, value));
    volumeRef.current = nextVolume;
    setVolumeState(nextVolume);
    if (audioRef.current) audioRef.current.volume = nextVolume;
    if (videoRef.current) videoRef.current.volume = nextVolume;
  }, []);

  const close = useCallback(() => {
    loadIdRef.current += 1;
    resetMedia();
    currentRef.current = null;
    retryRef.current = 0;
    setCurrent(null);
    setArtworkUrl(null);
    setMediaKind(null);
    applyQueue([], 0);
    setPlaying(false);
    setPosition(0);
    setDuration(0);
  }, [applyQueue, resetMedia, setPlaying]);

  /** Retry once after a media error, refreshing the signed URL. */
  const handleError = useCallback(() => {
    const track = currentRef.current;
    const media = mediaRef.current;
    if (!track || !media) return;

    const shouldResume = playingRef.current;
    setPlaying(false);
    if (retryRef.current >= 1) return;
    retryRef.current += 1;
    void loadSource(track, shouldResume, media.currentTime || 0);
  }, [loadSource, setPlaying]);

  // Keep the event handlers current without re-creating the media elements.
  endedRef.current = () => advance(true);
  errorRef.current = handleError;
  canPlayRef.current = () => {
    retryRef.current = 0;
  };

  useEffect(() => {
    const audio = getAudio();
    const video = getVideo();
    audio.volume = volumeRef.current;
    video.volume = volumeRef.current;
    setVideoElement(video);

    const onTimeUpdate = (event: Event) => {
      if (event.currentTarget !== mediaRef.current) return;
      setPosition((event.currentTarget as HTMLMediaElement).currentTime || 0);
    };
    const onDurationChange = (event: Event) => {
      if (event.currentTarget !== mediaRef.current) return;
      const media = event.currentTarget as HTMLMediaElement;
      setDuration(
        Number.isFinite(media.duration) && media.duration > 0
          ? media.duration
          : currentRef.current?.duration_seconds ?? 0,
      );
    };
    const onPlay = (event: Event) => {
      if (event.currentTarget !== mediaRef.current) return;
      setPlaying(true);
    };
    const onPause = (event: Event) => {
      if (event.currentTarget !== mediaRef.current) return;
      setPlaying(false);
    };
    const onEnded = (event: Event) => {
      if (event.currentTarget !== mediaRef.current) return;
      endedRef.current();
    };
    const onError = (event: Event) => {
      if (event.currentTarget !== mediaRef.current) return;
      errorRef.current();
    };
    const onCanPlay = (event: Event) => {
      if (event.currentTarget !== mediaRef.current) return;
      canPlayRef.current();
    };

    const elements = [audio, video];
    for (const element of elements) {
      element.addEventListener("timeupdate", onTimeUpdate);
      element.addEventListener("loadedmetadata", onDurationChange);
      element.addEventListener("durationchange", onDurationChange);
      element.addEventListener("play", onPlay);
      element.addEventListener("pause", onPause);
      element.addEventListener("ended", onEnded);
      element.addEventListener("error", onError);
      element.addEventListener("canplay", onCanPlay);
    }

    return () => {
      for (const element of elements) {
        element.removeEventListener("timeupdate", onTimeUpdate);
        element.removeEventListener("loadedmetadata", onDurationChange);
        element.removeEventListener("durationchange", onDurationChange);
        element.removeEventListener("play", onPlay);
        element.removeEventListener("pause", onPause);
        element.removeEventListener("ended", onEnded);
        element.removeEventListener("error", onError);
        element.removeEventListener("canplay", onCanPlay);
        element.pause();
        element.removeAttribute("src");
        element.load();
      }
      mediaRef.current = null;
      audioRef.current = null;
      videoRef.current = null;
      releaseBlobUrl();
      loadIdRef.current += 1;
    };
  }, [getAudio, getVideo, releaseBlobUrl, setPlaying]);

  const value = useMemo<PlayerContextValue>(
    () => ({
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
      playTrack,
      togglePlay,
      next,
      previous,
      seek,
      setVolume,
      close,
    }),
    [
      artworkUrl,
      close,
      current,
      duration,
      index,
      isPlaying,
      mediaKind,
      next,
      playTrack,
      position,
      previous,
      queue,
      seek,
      setVolume,
      togglePlay,
      videoElement,
      volume,
    ],
  );

  return (
    <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
  );
}

export function usePlayer(): PlayerContextValue {
  const value = useContext(PlayerContext);
  if (!value) {
    throw new Error("usePlayer must be used inside a PlayerProvider");
  }
  return value;
}
