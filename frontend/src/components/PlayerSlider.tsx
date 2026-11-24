/** `0:00` / `1:02:03` clock used by the player's time rows. */
export function formatClock(seconds: number): string {
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
export default function PlayerSlider({
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
