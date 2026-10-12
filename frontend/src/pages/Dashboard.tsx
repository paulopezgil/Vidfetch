import { useCallback, useEffect, useRef, useState } from "react";
import type { FormatName, InfoResult, OperationType, Task } from "../types";
import { isTerminal } from "../lib";
import {
  cancelTask,
  fetchInfo,
  listTasks,
  startDownload,
  streamTask,
} from "../api";
import UrlInput from "../components/UrlInput";
import InfoPreview from "../components/InfoPreview";
import TaskCard from "../components/TaskCard";
import EmptyState from "../components/EmptyState";
import Spinner from "../components/Spinner";
import { useToast } from "../components/Toast";

export default function Dashboard() {
  const toast = useToast();
  const [info, setInfo] = useState<InfoResult | null>(null);
  const [infoLoading, setInfoLoading] = useState(false);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [submittedUrl, setSubmittedUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [tasks, setTasks] = useState<Record<string, Task>>({});
  const cleanups = useRef<Map<string, () => void>>(new Map());

  const subscribe = useCallback(
    (taskId: string) => {
      const cleanup = streamTask(
        taskId,
        (t) => setTasks((prev) => ({ ...prev, [t.task_id]: t })),
        () => {
          const finished = tasksRef.current[taskId];
          if (finished) {
            if (finished.status === "completed") {
              toast("Descàrrega completada", "success");
            } else if (finished.status === "failed") {
              toast(
                `La descàrrega ha fallat: ${finished.error || "error desconegut"}`,
                "error",
              );
            } else if (finished.status === "cancelled") {
              toast("Descàrrega cancel·lada", "info");
            }
          }
          window.setTimeout(() => {
            setTasks((prev) => {
              const next = { ...prev };
              delete next[taskId];
              return next;
            });
          }, 5000);
          cleanups.current.delete(taskId);
        },
      );
      cleanups.current.set(taskId, cleanup);
    },
    [toast],
  );

  // Keep a ref mirror of tasks so the SSE "done" callback can read final state.
  const tasksRef = useRef<Record<string, Task>>({});
  useEffect(() => {
    tasksRef.current = tasks;
  }, [tasks]);

  useEffect(() => {
    let cancelled = false;
    listTasks()
      .then((active) => {
        if (cancelled) return;
        active.forEach((t) => {
          setTasks((prev) => ({ ...prev, [t.task_id]: t }));
          subscribe(t.task_id);
        });
      })
      .catch(() => {
        // Ignore; the dashboard still works without live restore.
      });
    return () => {
      cancelled = true;
      cleanups.current.forEach((c) => c());
      cleanups.current.clear();
    };
  }, [subscribe]);

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
        subscribe(task_id);
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "No s’ha pogut iniciar la descàrrega",
          "error",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [submittedUrl, subscribe, toast],
  );

  const handleCancel = useCallback(
    async (taskId: string) => {
      try {
        await cancelTask(taskId);
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "No s’ha pogut cancel·lar la tasca",
          "error",
        );
      }
    },
    [toast],
  );

  const activeTasks = Object.values(tasks)
    .filter((t) => !isTerminal(t.status))
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

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
        {activeTasks.length > 0 ? (
          <div className="space-y-3">
            {activeTasks.map((t) => (
              <TaskCard key={t.task_id} task={t} onCancel={handleCancel} />
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
