import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Download,
  History as HistoryIcon,
  ListVideo,
  Film,
  RotateCw,
  Search,
} from "lucide-react";
import type { FormatName, HistoryEntry, OperationType } from "../types";
import { formatDate } from "../lib";
import { fileUrl, listHistory, startDownload } from "../api";
import Button from "../components/Button";
import StatusChip from "../components/StatusChip";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import IconButton from "../components/IconButton";
import Spinner from "../components/Spinner";
import { useToast } from "../components/Toast";

const PAGE = 25;

const filters = [
  { value: "", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

const formatLabels: Record<string, string> = {
  best: "Best",
  "720p": "720p",
  mp3: "MP3",
};

export default function History() {
  const toast = useToast();
  const [items, setItems] = useState<HistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  const load = useCallback(
    async (newOffset = offset, newStatus = status, newSearch = search) => {
      setLoading(true);
      try {
        const page = await listHistory({
          limit: PAGE,
          offset: newOffset,
          status: newStatus || undefined,
          search: newSearch || undefined,
        });
        setItems(page.items);
        setTotal(page.total);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load history");
      } finally {
        setLoading(false);
      }
    },
    [offset, status, search],
  );

  useEffect(() => {
    load(0, status, search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  function submitSearch(e: FormEvent) {
    e.preventDefault();
    setOffset(0);
    load(0, status, search);
  }

  async function retry(entry: HistoryEntry) {
    setRetrying(entry.task_id);
    try {
      await startDownload({
        url: entry.url,
        operation_type: entry.operation_type as OperationType,
        format: entry.format as FormatName,
        embed_subs: entry.embed_subs,
        playlist_id: entry.playlist_id || undefined,
      });
      toast("Retry started — track it on the Dashboard", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Retry failed", "error");
    } finally {
      setRetrying(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-fg">History</h1>
          <p className="mt-1 text-sm text-fg-secondary">
            A record of every download operation.
          </p>
        </div>
        <form
          onSubmit={submitSearch}
          className="flex w-full items-center gap-2 sm:w-auto"
        >
          <div className="relative flex-1 sm:flex-none">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search…"
              className="h-9 w-full rounded-lg border border-line bg-surface-1 pl-9 pr-3 text-sm text-fg placeholder:text-fg-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/50 sm:w-48"
            />
          </div>
          <Button type="submit" variant="secondary" size="sm">
            Search
          </Button>
        </form>
      </header>

      <div className="flex flex-wrap gap-1.5">
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => {
              setStatus(f.value);
              setOffset(0);
            }}
            className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/70 ${
              status === f.value
                ? "bg-brand/15 text-brand-hover"
                : "text-fg-secondary hover:bg-surface-2 hover:text-fg"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-fg-secondary">
          <Spinner className="mr-2" /> Loading history…
        </div>
      ) : error ? (
        <ErrorBanner
          message={error}
          onRetry={() => load(offset, status, search)}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<HistoryIcon className="h-6 w-6" />}
          title="No history yet"
          description="Completed and failed downloads will be recorded here."
        />
      ) : (
        <div className="card divide-y divide-line/60">
          {items.map((entry) => {
            const Icon =
              entry.operation_type === "playlist" ? ListVideo : Film;
            const canDownload = entry.file_exists && entry.output_filename;
            return (
              <div key={entry.task_id} className="flex items-start gap-3 px-4 py-3.5">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-fg-muted">
                  <Icon className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-fg">
                      {entry.title || entry.url}
                    </p>
                    <StatusChip status={entry.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-fg-muted">
                    {formatDate(entry.created_at)}
                    {" · "}
                    {entry.operation_type === "playlist"
                      ? "Playlist"
                      : entry.operation_type === "playlist_item"
                        ? "Playlist item"
                        : "Video"}
                    {" · "}
                    {formatLabels[entry.format] ?? entry.format}
                    {entry.output_filename
                      ? ` · ${entry.output_filename}`
                      : ""}
                  </p>
                  {entry.status === "failed" && entry.error ? (
                    <p className="mt-1 text-xs text-danger">{entry.error}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {canDownload ? (
                    <IconButton
                      href={fileUrl(entry.output_filename)}
                      label="Download file"
                    >
                      <Download className="h-4 w-4" />
                    </IconButton>
                  ) : null}
                  {entry.status === "failed" ? (
                    <button
                      onClick={() => retry(entry)}
                      disabled={retrying === entry.task_id}
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-2.5 text-[13px] font-medium text-fg transition-colors hover:bg-line/60 disabled:opacity-50"
                    >
                      {retrying === entry.task_id ? (
                        <Spinner />
                      ) : (
                        <RotateCw className="h-4 w-4" />
                      )}
                      Retry
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {total > PAGE ? (
        <div className="flex items-center justify-between text-sm text-fg-secondary">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={offset === 0}
              onClick={() => {
                const next = Math.max(0, offset - PAGE);
                setOffset(next);
                load(next, status, search);
              }}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={offset + PAGE >= total}
              onClick={() => {
                const next = offset + PAGE;
                setOffset(next);
                load(next, status, search);
              }}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
