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

/** `audio.play()` rejects on autoplay policy or a replaced source. */
function attemptPlay(audio: HTMLAudioElement): void {
  const result = audio.play();
  if (result && typeof result.catch === "function") {
    result.catch(() => {
      // The bar simply stays paused; the user can retry.
    });
  }
}

/**
 * Single persistent audio element shared by every route in the app shell.
 *
 * The provider owns playback state, a queue with auto-advance, and the
 * short-lived signed URL refresh. Token or network failures never throw into
 * the UI: the bar stays visible and paused.
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

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const currentRef = useRef<Track | null>(null);
  const playingRef = useRef(false);
  const queueRef = useRef<Track[]>([]);
  const indexRef = useRef(0);
  const volumeRef = useRef(1);
  const expiresAtRef = useRef(0);
  const loadIdRef = useRef(0);
  const retryRef = useRef(0);

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

  const applyQueue = useCallback((nextQueue: Track[], nextIndex: number) => {
    queueRef.current = nextQueue;
    indexRef.current = nextIndex;
    setQueue(nextQueue);
    setIndex(nextIndex);
  }, []);

  /** Load a signed source for `track`, optionally resuming mid-track. */
  const loadSource = useCallback(
    async (track: Track, autoplay: boolean, resumeAt = 0) => {
      const audio = audioRef.current;
      if (!audio) return;

      const loadId = ++loadIdRef.current;
      const startAt =
        Number.isFinite(resumeAt) && resumeAt > 0 ? resumeAt : 0;

      // Stop whatever was loaded before, so a failed token request can never
      // leave the previous track playing behind a paused bar.
      audio.pause();
      audio.removeAttribute("src");
      expiresAtRef.current = 0;

      currentRef.current = track;
      setCurrent(track);
      setArtworkUrl(null);
      setDuration(track.duration_seconds ?? 0);
      setPosition(startAt);
      setPlaying(false);

      try {
        const token = await getMediaToken(track.asset_id);
        if (loadId !== loadIdRef.current) return;

        expiresAtRef.current = tokenExpiry(token);
        setArtworkUrl(token.thumbnail_url ?? null);
        audio.src = token.url;
        audio.load();

        if (startAt > 0) {
          const onMetadata = () => {
            audio.removeEventListener("loadedmetadata", onMetadata);
            if (loadId !== loadIdRef.current) return;
            try {
              audio.currentTime = startAt;
            } catch {
              // Seeking before the media is ready is not fatal.
            }
          };
          audio.addEventListener("loadedmetadata", onMetadata);
        }

        if (autoplay) attemptPlay(audio);
      } catch {
        if (loadId !== loadIdRef.current) return;
        // The signed URL could not be minted. Keep the track in the bar, but
        // paused and silent; nothing is surfaced to the user.
        expiresAtRef.current = 0;
        setPlaying(false);
      }
    },
    [setPlaying],
  );

  const seek = useCallback(
    (seconds: number) => {
      const audio = audioRef.current;
      if (!audio) return;
      const max =
        Number.isFinite(audio.duration) && audio.duration > 0
          ? audio.duration
          : currentRef.current?.duration_seconds ?? 0;
      const next = Math.max(0, max > 0 ? Math.min(seconds, max) : seconds);
      try {
        audio.currentTime = next;
      } catch {
        return;
      }
      setPosition(next);
    },
    [],
  );

  const advance = useCallback(
    (autoplay: boolean) => {
      const currentQueue = queueRef.current;
      if (currentQueue.length === 0) return;

      const nextIndex = indexRef.current + 1;
      if (nextIndex >= currentQueue.length) {
        // End of the queue: stop on the last item instead of looping.
        const audio = audioRef.current;
        if (audio) {
          audio.pause();
          setPosition(
            Number.isFinite(audio.duration) && audio.duration > 0
              ? audio.duration
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
    const audio = audioRef.current;
    if (!audio) return;
    // Like most players: restart the current item unless we are near its start.
    if (audio.currentTime > 3 || indexRef.current === 0) {
      seek(0);
      return;
    }
    const previousIndex = Math.max(0, indexRef.current - 1);
    retryRef.current = 0;
    applyQueue(queueRef.current, previousIndex);
    void loadSource(queueRef.current[previousIndex], playingRef.current);
  }, [applyQueue, loadSource, seek]);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    const track = currentRef.current;
    if (!audio || !track) return;
    if (!audio.paused) {
      audio.pause();
      return;
    }
    if (!audio.src || isExpired(expiresAtRef.current)) {
      void loadSource(track, true, audio.ended ? 0 : audio.currentTime || 0);
      return;
    }
    if (audio.ended) seek(0);
    attemptPlay(audio);
  }, [loadSource, seek]);

  const playTrack = useCallback(
    (track: Track, nextQueue?: Track[]) => {
      const audio = audioRef.current;
      if (!audio) return;

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
        if (!audio.paused) {
          audio.pause();
          return;
        }
        retryRef.current = 0;
        if (!audio.src || isExpired(expiresAtRef.current)) {
          void loadSource(
            track,
            true,
            audio.ended ? 0 : audio.currentTime || 0,
          );
          return;
        }
        if (audio.ended) seek(0);
        attemptPlay(audio);
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
  }, []);

  const close = useCallback(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    loadIdRef.current += 1;
    currentRef.current = null;
    expiresAtRef.current = 0;
    retryRef.current = 0;
    setCurrent(null);
    setArtworkUrl(null);
    applyQueue([], 0);
    setPlaying(false);
    setPosition(0);
    setDuration(0);
  }, [applyQueue, setPlaying]);

  /** Retry once after a media error, refreshing the signed URL. */
  const handleError = useCallback(() => {
    const track = currentRef.current;
    const audio = audioRef.current;
    if (!track || !audio) return;

    const shouldResume = playingRef.current;
    setPlaying(false);
    if (retryRef.current >= 1) return;
    retryRef.current += 1;
    void loadSource(track, shouldResume, audio.currentTime || 0);
  }, [loadSource, setPlaying]);

  // Keep the event handlers current without re-creating the audio element.
  endedRef.current = () => advance(true);
  errorRef.current = handleError;
  canPlayRef.current = () => {
    retryRef.current = 0;
  };

  useEffect(() => {
    const audio = getAudio();
    audio.volume = volumeRef.current;

    const onTimeUpdate = () => setPosition(audio.currentTime || 0);
    const onDurationChange = () => {
      setDuration(
        Number.isFinite(audio.duration) && audio.duration > 0
          ? audio.duration
          : currentRef.current?.duration_seconds ?? 0,
      );
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => endedRef.current();
    const onError = () => errorRef.current();
    const onCanPlay = () => canPlayRef.current();

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onDurationChange);
    audio.addEventListener("durationchange", onDurationChange);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    audio.addEventListener("canplay", onCanPlay);

    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onDurationChange);
      audio.removeEventListener("durationchange", onDurationChange);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      audio.removeEventListener("canplay", onCanPlay);
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      audioRef.current = null;
      loadIdRef.current += 1;
    };
  }, [getAudio, setPlaying]);

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
      next,
      playTrack,
      position,
      previous,
      queue,
      seek,
      setVolume,
      togglePlay,
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
