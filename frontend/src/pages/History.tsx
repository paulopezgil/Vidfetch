import { useCallback, useEffect, useState } from "react";
import type { DownloadJob, DownloadJobStatus } from "../types/v2";
import { isActiveJob } from "../types/v2";
import { formatBytes, formatDate } from "../lib";
import { listDownloads } from "../lib/api";
import Button from "../components/Button";
import StatusChip from "../components/StatusChip";
import ProgressBar from "../components/ProgressBar";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import Card from "../components/Card";
import FilterChip from "../components/FilterChip";
import SearchBar from "../components/SearchBar";
import Spinner from "../components/Spinner";

const PAGE = 25;

type StatusFilter = "" | DownloadJobStatus;

const filters: { value: StatusFilter; label: string }[] = [
  { value: "", label: "Tot" },
  { value: "queued", label: "En cua" },
  { value: "resolving", label: "Resolent" },
  { value: "downloading", label: "Descarregant" },
  { value: "processing", label: "Processant" },
  { value: "ready", label: "A punt" },
  { value: "failed", label: "Fallides" },
  { value: "cancelled", label: "Cancel·lades" },
];

/** Human label for the kind of job in a history row. */
function kindLabel(job: DownloadJob): string {
  if (job.kind === "playlist") return "Llista de reproducció";
  if (job.kind === "playlist_item") return "Vídeo de la llista";
  return "Vídeo";
}

export default function History() {
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<StatusFilter>("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (newOffset = offset, newStatus = status) => {
      setLoading(true);
      try {
        const page = await listDownloads({
          status: newStatus || undefined,
          limit: PAGE,
          offset: newOffset,
        });
        setJobs(page.items);
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
    [offset, status],
  );

  useEffect(() => {
    load(0, status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  function runSearch() {
    setOffset(0);
    load(0, status);
  }

  // The v2 downloads endpoint filters by status and paginates, but has no
  // free-text query. Search is therefore client-side over the current page
  // only (`title` / `current_item_title`); older matches need paging.
  const query = search.trim().toLocaleLowerCase("ca-ES");
  const visibleJobs = query
    ? jobs.filter((job) =>
        [job.title, job.current_item_title]
          .filter(Boolean)
          .some((text) => text.toLocaleLowerCase("ca-ES").includes(query)),
      )
    : jobs;

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
        <ErrorBanner message={error} onRetry={() => load(offset, status)} />
      ) : jobs.length === 0 ? (
        <EmptyState
          icon="history"
          title="Encara no hi ha historial"
          description="Les descàrregues que iniciïs es registraran aquí, amb el seu estat i progrés."
        />
      ) : visibleJobs.length === 0 ? (
        <EmptyState
          icon="search_off"
          title="Cap resultat en aquesta pàgina"
          description="La cerca només recorre la pàgina actual. Prova una altra pàgina o buida la cerca."
        />
      ) : (
        <Card
          variant="outlined"
          className="divide-y divide-outline-variant overflow-hidden"
        >
          {visibleJobs.map((job) => (
            <JobRow key={job.id} job={job} />
          ))}
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
                load(next, status);
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
                load(next, status);
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

function JobRow({ job }: { job: DownloadJob }) {
  const active = isActiveJob(job.status);
  const waiting =
    (job.status === "queued" || job.status === "resolving") &&
    job.progress === 0;
  const title = job.title || job.source_url || "Descàrrega sense títol";
  const icon = job.kind === "playlist" ? "playlist_play" : "movie";
  const itemLabel =
    job.kind === "playlist" && job.current_item_title
      ? `Vídeo ${Math.max(job.item_index, 1)}${
          job.item_count > 0 ? ` de ${job.item_count}` : ""
        } — ${job.current_item_title}`
      : "";

  return (
    <div className="flex items-start gap-3 p-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-container-high text-on-surface-variant">
        <Icon name={icon} className="text-[20px]" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-body-large text-on-surface">{title}</p>
          <StatusChip status={job.status} />
        </div>
        <p className="mt-0.5 text-label-medium text-on-surface-variant">
          {formatDate(job.created_at)}
          {" · "}
          {kindLabel(job)}
          {job.kind === "playlist" && job.item_count > 0
            ? ` · ${job.item_count} vídeos`
            : ""}
        </p>

        {active ? (
          <div className="mt-2 space-y-1">
            <ProgressBar
              value={job.progress}
              indeterminate={waiting}
              label={`Progrés de la descàrrega de ${title}`}
            />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-label-medium text-on-surface-variant">
              {waiting ? (
                <span>En curs…</span>
              ) : (
                <span className="tabular-nums">
                  {job.progress.toFixed(0)}%
                </span>
              )}
              {job.downloaded_bytes > 0 ? (
                <span className="tabular-nums">
                  {formatBytes(job.downloaded_bytes)}
                  {job.total_bytes
                    ? ` / ${formatBytes(job.total_bytes)}`
                    : ""}
                </span>
              ) : null}
            </div>
            {itemLabel ? (
              <p className="truncate text-body-small text-on-surface-variant">
                {itemLabel}
              </p>
            ) : null}
          </div>
        ) : null}

        {job.status === "failed" && job.error ? (
          <p
            role="alert"
            className="mt-1 line-clamp-3 text-body-small text-error"
          >
            {job.error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
