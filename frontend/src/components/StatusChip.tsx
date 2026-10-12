import { STATUS_LABELS } from "../lib";
import Icon from "./Icon";

const active = new Set([
  "queued",
  "fetching information",
  "downloading",
  "processing",
  "packaging zip",
]);

const styles: Record<string, string> = {
  queued: "bg-surface-container-highest text-on-surface-variant",
  "fetching information": "bg-primary-container text-on-primary-container",
  downloading: "bg-primary-container text-on-primary-container",
  processing: "bg-primary-container text-on-primary-container",
  "packaging zip": "bg-primary-container text-on-primary-container",
  completed: "bg-success-container text-on-success-container",
  failed: "bg-error-container text-on-error-container",
  cancelled: "bg-surface-container-highest text-on-surface-variant",
  pending: "bg-surface-container-highest text-on-surface-variant",
  downloaded: "bg-success-container text-on-success-container",
  missing: "bg-warning-container text-on-warning-container",
};

const icons: Record<string, string> = {
  queued: "schedule",
  "fetching information": "sync",
  downloading: "download",
  processing: "sync",
  "packaging zip": "folder_zip",
  completed: "check_circle",
  failed: "error",
  cancelled: "cancel",
  pending: "radio_button_unchecked",
  downloaded: "check_circle",
  missing: "warning",
};

/** Status is communicated with an icon and label, never color alone. */
export default function StatusChip({ status }: { status: string }) {
  const style = styles[status] ?? "bg-surface-container-highest text-on-surface-variant";
  const icon = icons[status] ?? "circle";
  const label = STATUS_LABELS[status] ?? status;
  const pulse = active.has(status);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-label-medium ${style}`}
    >
      <Icon
        name={icon}
        className={`text-[16px] ${pulse ? "animate-pulse" : ""}`}
      />
      {label}
    </span>
  );
}
