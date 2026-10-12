import { STATUS_LABELS } from "../lib";

const active = new Set([
  "queued",
  "fetching information",
  "downloading",
  "processing",
  "packaging zip",
]);

const styles: Record<string, string> = {
  queued: "bg-fg-muted/15 text-fg-muted",
  "fetching information": "bg-info/15 text-info",
  downloading: "bg-brand/15 text-brand-hover",
  processing: "bg-info/15 text-info",
  "packaging zip": "bg-info/15 text-info",
  completed: "bg-success/15 text-success",
  failed: "bg-danger/15 text-danger",
  cancelled: "bg-fg-muted/15 text-fg-muted",
  pending: "bg-fg-muted/15 text-fg-muted",
  downloaded: "bg-success/15 text-success",
  missing: "bg-warning/15 text-warning",
};

export default function StatusChip({ status }: { status: string }) {
  const style = styles[status] ?? "bg-fg-muted/15 text-fg-muted";
  const label = STATUS_LABELS[status] ?? status;
  const pulse = active.has(status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${style}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full bg-current ${pulse ? "animate-pulse" : ""}`}
      />
      {label}
    </span>
  );
}
