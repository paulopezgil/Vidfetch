import { useCallback, useEffect, useRef, useState } from "react";
import type { Track } from "../types/v2";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Menu from "./Menu";
import Thumbnail from "./Thumbnail";
import TrackEditDialog from "./TrackEditDialog";
import { useToast } from "./Toast";
import PlayerSlider, { formatClock } from "./PlayerSlider";
import { usePlayer } from "../player/PlayerProvider";

interface NowPlayingPanelProps {
  /** Whether the full-screen player is open. */
  expanded: boolean;
  /** Minimize the full-screen player; the docked bar stays usable behind it. */
  onToggle: () => void;
}

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Full-screen now-playing surface for songs.
 *
 * Songs get a dedicated immersive view with large artwork, metadata, and
 * transport controls. Volume deliberately lives on the docked bar only; this
 * surface is about the track, not device settings. Videos render in
 * `VideoSurface` instead, so this panel never mounts the provider video element.
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
    togglePlay,
    next,
    previous,
    seek,
    updateTrack,
  } = usePlayer();

  const toast = useToast();
  const [editing, setEditing] = useState<Track | null>(null);

  const panelRef = useRef<HTMLDivElement | null>(null);
  const minimizeRef = useRef<HTMLButtonElement | null>(null);
  const onToggleRef = useRef(onToggle);
  /** Lets the key handler ignore Esc/Tab while the edit dialog is on top. */
  const editingRef = useRef(editing);
  editingRef.current = editing;

  useEffect(() => {
    onToggleRef.current = onToggle;
  }, [onToggle]);

  const handleSaved = useCallback(
    (track: Track) => {
      // Refresh the title/artist/album/cover here without reloading the audio.
      updateTrack(track);
      toast("Track actualitzat", "success");
    },
    [toast, updateTrack],
  );

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
      // The edit dialog owns Escape and Tab while it is open.
      if (editingRef.current) return;
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
      <IconButton label="Pista anterior" onClick={previous}>
        <Icon name="skip_previous" className="text-[24px]" />
      </IconButton>
      <IconButton
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
        <div className="flex shrink-0 items-center gap-1">
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
            buttonRef={minimizeRef}
            label="Minimitza el reproductor"
            title="Minimitza el reproductor"
            onClick={onToggle}
          >
            <Icon name="expand_more" className="text-[24px]" />
          </IconButton>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-6 overflow-y-auto px-4 py-6 sm:px-6">
        <Thumbnail
          src={cover}
          icon="music_note"
          className="h-56 w-56 sm:h-72 sm:w-72 lg:h-80 lg:w-80"
        />
        <div className="w-full max-w-xl space-y-4 text-center">
          <div className="min-w-0">
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
          <div className="flex items-center gap-2">{seekRow}</div>
          <div className="flex items-center justify-center gap-1">
            {transportControls}
          </div>
        </div>
      </div>

      <TrackEditDialog
        open={editing !== null}
        track={editing}
        onClose={() => setEditing(null)}
        onSaved={handleSaved}
      />
    </div>
  );
}
