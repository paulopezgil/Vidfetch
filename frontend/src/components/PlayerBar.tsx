import Icon from "./Icon";
import IconButton from "./IconButton";
import Thumbnail from "./Thumbnail";
import { usePlayer } from "../player/PlayerProvider";

/** `0:00` / `1:02:03` clock used by the seek row. */
function clock(seconds: number): string {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  const ss = String(secs).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${ss}`;
  }
  return `${minutes}:${ss}`;
}

interface PlayerSliderProps {
  label: string;
  value: number;
  max: number;
  step?: number;
  disabled?: boolean;
  valueText?: string;
  onChange: (value: number) => void;
}

/**
 * Native range input styled with Material 3 semantic roles. Keeping the native
 * element preserves keyboard support and screen-reader slider semantics.
 */
function PlayerSlider({
  label,
  value,
  max,
  step = 1,
  disabled,
  valueText,
  onChange,
}: PlayerSliderProps) {
  const upper = Math.max(max, 0.01);
  const clamped = Math.min(Math.max(value, 0), upper);

  return (
    <input
      type="range"
      min={0}
      max={upper}
      step={step}
      value={clamped}
      disabled={disabled}
      aria-label={label}
      aria-valuetext={valueText}
      onChange={(event) => onChange(Number(event.target.value))}
      className="h-4 w-full cursor-pointer appearance-none rounded-full bg-transparent accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface-container-high disabled:cursor-not-allowed disabled:opacity-[0.38] [&::-moz-range-thumb]:h-3 [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-primary [&::-moz-range-track]:h-1 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-outline-variant [&::-webkit-slider-runnable-track]:h-1 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-outline-variant [&::-webkit-slider-thumb]:mt-[-4px] [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary"
    />
  );
}

/**
 * Persistent playback bar. Docked above the compact navigation bar and inside
 * the content column on wider windows, so it never covers the rail/drawer.
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
    togglePlay,
    next,
    previous,
    seek,
    setVolume,
    close,
  } = usePlayer();

  const hasTrack = current !== null;
  const hasNext = hasTrack && index < queue.length - 1;
  const artist = current?.artist?.trim() || "Unknown artist";
  const seekable = hasTrack && duration > 0;

  const controls = (
    <>
      <IconButton
        label="Previous track"
        onClick={previous}
        disabled={!hasTrack}
      >
        <Icon name="skip_previous" className="text-[22px]" />
      </IconButton>
      <IconButton
        variant="filled"
        size="md"
        label={isPlaying ? "Pause" : "Play"}
        onClick={togglePlay}
        disabled={!hasTrack}
      >
        <Icon
          name={isPlaying ? "pause" : "play_arrow"}
          filled
          className="text-[24px]"
        />
      </IconButton>
      <IconButton label="Next track" onClick={next} disabled={!hasNext}>
        <Icon name="skip_next" className="text-[22px]" />
      </IconButton>
    </>
  );

  const seekRow = (
    <>
      <span className="w-12 shrink-0 text-right text-label-medium tabular-nums text-on-surface-variant">
        {clock(hasTrack ? position : 0)}
      </span>
      <PlayerSlider
        label="Seek"
        value={hasTrack ? position : 0}
        max={seekable ? duration : 0}
        disabled={!seekable}
        valueText={`${clock(hasTrack ? position : 0)} of ${clock(
          seekable ? duration : 0,
        )}`}
        onChange={seek}
      />
      <span className="w-12 shrink-0 text-label-medium tabular-nums text-on-surface-variant">
        {clock(seekable ? duration : 0)}
      </span>
    </>
  );

  return (
    <section
      aria-label="Player"
      className="shrink-0 border-t border-outline-variant bg-surface-container-high"
    >
      <div className="flex items-center gap-3 px-3 py-2 sm:px-4">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:w-56 sm:flex-none lg:w-64">
          <Thumbnail
            src={hasTrack ? artworkUrl : null}
            icon="music_note"
            className={`h-12 w-12 ${hasTrack ? "" : "opacity-60"}`}
          />
          <div className="min-w-0 flex-1">
            <p
              className={`truncate text-title-small ${
                hasTrack ? "text-on-surface" : "text-on-surface-variant"
              }`}
            >
              {hasTrack ? current.title : "Nothing playing"}
            </p>
            <p className="truncate text-body-small text-on-surface-variant">
              {hasTrack ? artist : "Choose a track to start listening"}
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

        <div className="hidden w-56 shrink-0 items-center justify-end gap-1 md:flex">
          <Icon
            name={volume === 0 ? "volume_off" : "volume_up"}
            className="text-[20px] text-on-surface-variant"
          />
          <div className="w-24">
            <PlayerSlider
              label="Volume"
              value={volume}
              max={1}
              step={0.01}
              valueText={`${Math.round(volume * 100)}%`}
              onChange={setVolume}
            />
          </div>
          <IconButton
            label="Close player"
            onClick={close}
            disabled={!hasTrack}
          >
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>
      </div>

      <div className="flex items-center gap-2 px-3 pb-2 sm:hidden">
        {seekRow}
      </div>
    </section>
  );
}
