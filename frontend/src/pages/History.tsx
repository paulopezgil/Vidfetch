import { useCallback, useEffect, useState } from "react";
import type { FormatName, HistoryEntry, OperationType } from "../types";
import { formatDate } from "../lib";
import { fileUrl, listHistory, startDownload } from "../api";
import Button from "../components/Button";
import StatusChip from "../components/StatusChip";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import IconButton from "../components/IconButton";
import Icon from "../components/Icon";
import Card from "../components/Card";
import FilterChip from "../components/FilterChip";
import SearchBar from "../components/SearchBar";
import Spinner from "../components/Spinner";
import { useToast } from "../components/Toast";

const PAGE = 25;

const filters = [
  { value: "", label: "Tot" },
  { value: "completed", label: "Completades" },
  { value: "failed", label: "Fallides" },
];

const formatLabels: Record<string, string> = {
  best: "Millor",
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
        setError(
          e instanceof Error ? e.message : "No s’ha pogut carregar l’historial",
        );
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

  function runSearch() {
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
      toast("Nou intent iniciat: segueix-lo a l’Inici", "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "No s’ha pogut reintentar", "error");
    } finally {
      setRetrying(null);
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <SearchBar
        value={search}
        onChange={setSearch}
        onSubmit={runSearch}
        label="Cerca a l’historial"
        placeholder="Cerca a l’historial"
        submitLabel="Cerca"
      />

      <div className="flex gap-2 overflow-x-auto pb-1">
        {filters.map((f) => (
          <FilterChip
            key={f.value}
            label={f.label}
            selected={status === f.value}
            onClick={() => {
              setStatus(f.value);
              setOffset(0);
            }}
          />
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-3 py-16 text-body-medium text-on-surface-variant">
          <Spinner /> S’està carregant l’historial…
        </div>
      ) : error ? (
        <ErrorBanner
          message={error}
          onRetry={() => load(offset, status, search)}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon="history"
          title="Encara no hi ha historial"
          description="Les descàrregues completades i les que hagin fallat es registraran aquí."
        />
      ) : (
        <Card
          variant="outlined"
          className="divide-y divide-outline-variant overflow-hidden"
        >
          {items.map((entry) => {
            const icon =
              entry.operation_type === "playlist" ? "playlist_play" : "movie";
            const canDownload = entry.file_exists && entry.output_filename;
            return (
              <div key={entry.task_id} className="flex items-start gap-3 p-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-container-high text-on-surface-variant">
                  <Icon name={icon} className="text-[20px]" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-body-large text-on-surface">
                      {entry.title || entry.url}
                    </p>
                    <StatusChip status={entry.status} />
                  </div>
                  <p className="mt-0.5 text-label-medium text-on-surface-variant">
                    {formatDate(entry.created_at)}
                    {" · "}
                    {entry.operation_type === "playlist"
                      ? "Llista de reproducció"
                      : entry.operation_type === "playlist_item"
                        ? "Element de la llista"
                        : "Vídeo"}
                    {" · "}
                    {formatLabels[entry.format] ?? entry.format}
                    {entry.output_filename
                      ? ` · ${entry.output_filename}`
                      : ""}
                  </p>
                  {entry.status === "failed" && entry.error ? (
                    <p className="mt-1 text-body-small text-error">
                      {entry.error}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {canDownload ? (
                    <IconButton
                      href={fileUrl(entry.output_filename)}
                      variant="tonal"
                      label="Descarrega el fitxer"
                    >
                      <Icon name="download" className="text-[20px]" />
                    </IconButton>
                  ) : null}
                  {entry.status === "failed" ? (
                    <Button
                      variant="outlined"
                      size="sm"
                      onClick={() => retry(entry)}
                      disabled={retrying === entry.task_id}
                    >
                      {retrying === entry.task_id ? (
                        <Spinner />
                      ) : (
                        <Icon name="refresh" className="text-[18px]" />
                      )}
                      Torna-ho a provar
                    </Button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </Card>
      )}

      {total > PAGE ? (
        <div className="flex items-center justify-between text-body-medium text-on-surface-variant">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, total)} de {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outlined"
              size="sm"
              disabled={offset === 0}
              onClick={() => {
                const next = Math.max(0, offset - PAGE);
                setOffset(next);
                load(next, status, search);
              }}
            >
              Anterior
            </Button>
            <Button
              variant="outlined"
              size="sm"
              disabled={offset + PAGE >= total}
              onClick={() => {
                const next = offset + PAGE;
                setOffset(next);
                load(next, status, search);
              }}
            >
              Següent
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
