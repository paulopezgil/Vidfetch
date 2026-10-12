export function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function formatEta(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return "";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
  }
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
}

export function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ca-ES", { dateStyle: "medium", timeStyle: "short" });
}

export function formatSpeed(bytesPerSec: number): string {
  if (!bytesPerSec || bytesPerSec <= 0) return "";
  return `${formatBytes(bytesPerSec)}/s`;
}

export const STATUS_LABELS: Record<string, string> = {
  queued: "En cua",
  "fetching information": "Obtenint informació",
  downloading: "Descarregant",
  processing: "Processant",
  "packaging zip": "Empaquetant el ZIP",
  completed: "Completat",
  failed: "Fallit",
  cancelled: "Cancel·lat",
  pending: "No descarregat",
  downloaded: "Descarregat",
  missing: "Fitxer no trobat",
};

export function isTerminal(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}
