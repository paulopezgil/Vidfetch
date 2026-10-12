import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Link2 } from "lucide-react";
import type {
  FormatName,
  InfoResult,
  OperationType,
  Task,
} from "../types";
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
              toast("Download completed", "success");
            } else if (finished.status === "failed") {
              toast(`Download failed: ${finished.error || "unknown error"}`, "error");
            } else if (finished.status === "cancelled") {
              toast("Download cancelled", "info");
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
      setInfoError(e instanceof Error ? e.message : "Failed to fetch information.");
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
        toast("Download started", "info");
        subscribe(task_id);
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "Failed to start download",
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
        toast(e instanceof Error ? e.message : "Could not cancel task", "error");
      }
    },
    [toast],
  );

  const activeTasks = Object.values(tasks)
    .filter((t) => !isTerminal(t.status))
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 sm:px-6">
      <header>
        <h1 className="text-xl font-semibold text-fg">Dashboard</h1>
        <p className="mt-1 text-sm text-fg-secondary">
          Download individual videos or entire playlists.
        </p>
      </header>

      <UrlInput onFetch={handleFetch} loading={infoLoading} error={infoError} />

      {infoLoading ? (
        <div className="card flex items-center justify-center gap-2 px-4 py-10 text-sm text-fg-secondary">
          <Spinner /> Fetching information…
        </div>
      ) : null}

      {info ? (
        <InfoPreview
          info={info}
          submitting={submitting}
          onDownload={handleDownload}
        />
      ) : !infoLoading && !infoError ? (
        <EmptyState
          icon={<Link2 className="h-6 w-6" />}
          title="Nothing to preview yet"
          description="Paste a video or playlist URL above and choose “Fetch Info” to see its details."
        />
      ) : null}

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <Download className="h-4 w-4 text-fg-secondary" />
          <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-secondary">
            Active downloads
          </h2>
        </div>
        {activeTasks.length > 0 ? (
          <div className="space-y-3">
            {activeTasks.map((t) => (
              <TaskCard key={t.task_id} task={t} onCancel={handleCancel} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-fg-muted">No active downloads.</p>
        )}
      </section>
    </div>
  );
}
