import { useEffect, useState } from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Thumbnail from "./Thumbnail";
import PlayerSlider, { formatClock } from "./PlayerSlider";
import NowPlayingPanel from "./NowPlayingPanel";
import { usePlayer } from "../player/PlayerProvider";

/**
 * Persistent playback bar. Docked above the compact navigation bar and inside
 * the content column on wider windows, so it never covers the rail/drawer. The
 * expandable now-playing panel sits directly above the bar.
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

  const hasTrack = current !== null;
  const hasNext = hasTrack && index < queue.length - 1;
  const seekable = hasTrack && duration > 0;
  const trackId = current?.id ?? null;

  // Video needs its real surface visible as soon as it starts. Audio keeps the
  // panel collapsed unless the listener opens it from the bar.
  useEffect(() => {
    if (!trackId) {
      setExpanded(false);
      return;
    }
    if (mediaKind === "video") setExpanded(true);
  }, [mediaKind, trackId]);

  const credit = current
    ? [current.artist, current.album]
        .map((value) => value.trim())
        .filter((value) => value.length > 0)
        .join(" · ") || "Artista desconegut"
    : "Tria un track per començar a escoltar";
  const art = current?.cover_url ?? artworkUrl;

  const controls = (
    <>
      <IconButton
        label="Pista anterior"
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
      <IconButton label="Pista següent" onClick={next} disabled={!hasNext}>
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

  const expandButton = (
    <IconButton
      label={expanded ? "Amaga el reproductor" : "Mostra el reproductor"}
      onClick={() => setExpanded((value) => !value)}
      disabled={!hasTrack}
      ariaExpanded={expanded}
      ariaControls="now-playing-panel"
    >
      <Icon
        name={expanded ? "expand_more" : "expand_less"}
        className="text-[22px]"
      />
    </IconButton>
  );

  return (
    <section
      aria-label="Reproductor"
      className="shrink-0 border-t border-outline-variant bg-surface-container-high"
    >
      <NowPlayingPanel
        expanded={expanded}
        onToggle={() => setExpanded((value) => !value)}
      />

      <div className="flex items-center gap-3 px-3 py-2 sm:px-4">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:w-56 sm:flex-none lg:w-64">
          <Thumbnail
            src={hasTrack ? art : null}
            icon={mediaKind === "video" ? "movie" : "music_note"}
            className={`h-12 w-12 ${hasTrack ? "" : "opacity-60"}`}
          />
          <div className="min-w-0 flex-1">
            <p
              className={`truncate text-title-small ${
                hasTrack ? "text-on-surface" : "text-on-surface-variant"
              }`}
            >
              {hasTrack ? current.title : "No s’està reproduint res"}
            </p>
            <p className="truncate text-body-small text-on-surface-variant">
              {credit}
            </p>
          </div>
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
          {expandButton}
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
