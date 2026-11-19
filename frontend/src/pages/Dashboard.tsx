import { useCallback, useState } from "react";
import type { FormatName, InfoResult, OperationType } from "../types";
import { fetchInfo, startDownload } from "../api";
import UrlInput from "../components/UrlInput";
import InfoPreview from "../components/InfoPreview";
import TaskCard from "../components/TaskCard";
import EmptyState from "../components/EmptyState";
import Spinner from "../components/Spinner";
import { useToast } from "../components/Toast";
import { useActiveTasks } from "../components/ActiveTasks";

export default function Dashboard() {
  const toast = useToast();
  const { tasks, trackTask, cancelTask } = useActiveTasks();
  const [info, setInfo] = useState<InfoResult | null>(null);
  const [infoLoading, setInfoLoading] = useState(false);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [submittedUrl, setSubmittedUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleFetch = useCallback(async (url: string) => {
    setInfoLoading(true);
    setInfoError(null);
    setInfo(null);
    setSubmittedUrl(url);
    try {
      const result = await fetchInfo(url);
      setInfo(result);
    } catch (e) {
      setInfoError(
        e instanceof Error ? e.message : "No s’ha pogut obtenir la informació.",
      );
    } finally {
      setInfoLoading(false);
    }
  }, []);

  const handleDownload = useCallback(
    async (opts: {
      operation_type: OperationType;
      format: FormatName;
      embed_subs: boolean;
    }) => {
      if (!submittedUrl) return;
      setSubmitting(true);
      try {
        const { task_id } = await startDownload({
          url: submittedUrl,
          operation_type: opts.operation_type,
          format: opts.format,
          embed_subs: opts.embed_subs,
        });
        toast("Descàrrega iniciada", "info");
        trackTask(task_id);
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "No s’ha pogut iniciar la descàrrega",
          "error",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [submittedUrl, trackTask, toast],
  );

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <UrlInput onFetch={handleFetch} loading={infoLoading} error={infoError} />

      {infoLoading ? (
        <div className="flex items-center justify-center gap-3 py-10 text-body-medium text-on-surface-variant">
          <Spinner /> Obtenint informació…
        </div>
      ) : info ? (
        <InfoPreview
          info={info}
          submitting={submitting}
          onDownload={handleDownload}
        />
      ) : !infoError ? (
        <EmptyState
          icon="link"
          title="Encara no hi ha res per previsualitzar"
          description="Enganxa una URL de vídeo o de llista de reproducció a dalt per revisar-ne els detalls abans de descarregar."
        />
      ) : null}

      <section className="space-y-3">
        <h2 className="text-title-medium text-on-surface">
          Descàrregues actives
        </h2>
        {tasks.length > 0 ? (
          <div className="space-y-3">
            {tasks.map((t) => (
              <TaskCard key={t.task_id} task={t} onCancel={cancelTask} />
            ))}
          </div>
        ) : (
          <p className="text-body-medium text-on-surface-variant">
            No hi ha cap descàrrega activa.
          </p>
        )}
      </section>
    </div>
  );
}
