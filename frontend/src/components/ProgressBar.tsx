interface ProgressBarProps {
  value: number;
  status?: string;
  indeterminate?: boolean;
  /** Accessible name for the progress indicator. */
  label?: string;
}

/** Material 3 linear progress indicator. */
export default function ProgressBar({
  value,
  status,
  indeterminate = false,
  label = "Progrés",
}: ProgressBarProps) {
  const color =
    status === "failed"
      ? "bg-error"
      : status === "completed"
        ? "bg-success"
        : "bg-primary";

  if (indeterminate) {
    return (
      <div
        className="h-1 w-full overflow-hidden rounded-full bg-surface-container-highest"
        role="progressbar"
        aria-label={label}
        aria-valuetext="En curs"
      >
        <div className="h-full w-2/5 animate-[m3-indeterminate_1.6s_cubic-bezier(0.65,0,0.35,1)_infinite] rounded-full bg-primary" />
        <style>{`@keyframes m3-indeterminate{0%{margin-left:-45%}60%{margin-left:100%}100%{margin-left:100%}}`}</style>
      </div>
    );
  }

  const width = Math.min(Math.max(value, 0), 100);
  return (
    <div
      className="h-1 w-full overflow-hidden rounded-full bg-surface-container-highest"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(width)}
    >
      <div
        className={`h-full rounded-full transition-all duration-300 ${color}`}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}
