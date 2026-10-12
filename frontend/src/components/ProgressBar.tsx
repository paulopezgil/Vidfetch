interface ProgressBarProps {
  value: number;
  status?: string;
  indeterminate?: boolean;
  /** Accessible name for the progress indicator. */
  label?: string;
}

export default function ProgressBar({
  value,
  status,
  indeterminate = false,
  label = "Progress",
}: ProgressBarProps) {
  const color =
    status === "failed"
      ? "bg-danger"
      : status === "completed"
        ? "bg-success"
        : "bg-brand";

  if (indeterminate) {
    return (
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-label={label}
        aria-valuetext="In progress"
      >
        <div className="h-full w-1/3 animate-[slide_1.2s_ease-in-out_infinite] rounded-full bg-brand" />
        <style>{`@keyframes slide{0%{margin-left:-33%}100%{margin-left:100%}}`}</style>
      </div>
    );
  }

  const width = Math.min(Math.max(value, 0), 100);
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
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
