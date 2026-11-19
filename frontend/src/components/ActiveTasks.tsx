import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Task } from "../types";
import { isTerminal } from "../lib";
import {
  cancelTask as cancelTaskRequest,
  getTask,
  listTasks,
  streamTask,
} from "../api";
import { useToast } from "./Toast";

/** How long the "finished, it is in the library" notice stays visible. */
const FINISHED_NOTICE_MS = 8000;

/** How long a finished task stays in the store before it is dropped. */
const REMOVE_DELAY_MS = 5000;

export interface ActiveTasksValue {
  /** Active (non-terminal) tasks, oldest first. */
  tasks: Task[];
  /** Most recent task that reached a terminal state, for "it is in the library now" notices. */
  finishedTask: Task | null;
  /** Start tracking a freshly submitted task (idempotent). */
  trackTask: (taskId: string) => void;
  /** Request cancellation; failures are reported through a toast. */
  cancelTask: (taskId: string) => Promise<void>;
}

const ActiveTasksContext = createContext<ActiveTasksValue | null>(null);

export function useActiveTasks(): ActiveTasksValue {
  const value = useContext(ActiveTasksContext);
  if (!value) {
    throw new Error("useActiveTasks must be used inside <ActiveTasksProvider>");
  }
  return value;
}

/**
 * Owns active-download state for the whole app, so progress and completion
 * toasts survive navigation between pages.
 */
export function ActiveTasksProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [snapshot, setSnapshot] = useState<Record<string, Task>>({});
  const [finishedTask, setFinishedTask] = useState<Task | null>(null);

  // Authoritative store, written synchronously from every SSE callback. The
  // "done" handler reads from here instead of a ref mirror kept in sync by a
  // passive effect, which could lag one render behind the final snapshot.
  const latest = useRef<Record<string, Task>>({});
  const subscriptions = useRef(new Map<string, () => void>());
  const finalized = useRef(new Set<string>());

  const applyTask = useCallback((task: Task) => {
    latest.current = { ...latest.current, [task.task_id]: task };
    setSnapshot(latest.current);
  }, []);

  const removeTask = useCallback((taskId: string) => {
    if (!(taskId in latest.current)) return;
    const next = { ...latest.current };
    delete next[taskId];
    latest.current = next;
    finalized.current.delete(taskId);
    setSnapshot(next);
  }, []);

  const finishTask = useCallback(
    (taskId: string) => {
      if (finalized.current.has(taskId)) return;
      const task = latest.current[taskId];
      if (!task || !isTerminal(task.status)) return;
      finalized.current.add(taskId);

      if (task.status === "completed") {
        toast("Descàrrega completada", "success");
      } else if (task.status === "failed") {
        toast(
          `La descàrrega ha fallat: ${task.error || "error desconegut"}`,
          "error",
        );
      } else if (task.status === "cancelled") {
        toast("Descàrrega cancel·lada", "info");
      }

      setFinishedTask(task);
      window.setTimeout(() => removeTask(taskId), REMOVE_DELAY_MS);
      window.setTimeout(() => {
        setFinishedTask((current) =>
          current?.task_id === taskId ? null : current,
        );
      }, FINISHED_NOTICE_MS);
    },
    [toast, removeTask],
  );

  const handleDone = useCallback(
    async (taskId: string) => {
      subscriptions.current.delete(taskId);
      if (isTerminal(latest.current[taskId]?.status ?? "")) {
        finishTask(taskId);
        return;
      }
      // The stream closed before a terminal snapshot arrived; ask the API once.
      try {
        const task = await getTask(taskId);
        applyTask(task);
        finishTask(taskId);
      } catch {
        // Task already evicted; nothing sensible to show.
      }
    },
    [applyTask, finishTask],
  );

  const subscribe = useCallback(
    (taskId: string) => {
      if (subscriptions.current.has(taskId)) return;
      if (isTerminal(latest.current[taskId]?.status ?? "")) return;
      const cleanup = streamTask(
        taskId,
        (task) => applyTask(task),
        () => {
          void handleDone(taskId);
        },
      );
      subscriptions.current.set(taskId, cleanup);
    },
    [applyTask, handleDone],
  );

  const trackTask = useCallback(
    (taskId: string) => {
      subscribe(taskId);
      // Seed the card immediately instead of waiting for the first SSE frame.
      getTask(taskId)
        .then((task) => {
          applyTask(task);
          if (isTerminal(task.status)) void handleDone(taskId);
        })
        .catch(() => {
          // The SSE stream will surface the task if it still exists.
        });
    },
    [subscribe, applyTask, handleDone],
  );

  const cancelTask = useCallback(
    async (taskId: string) => {
      try {
        await cancelTaskRequest(taskId);
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "No s’ha pogut cancel·lar la tasca",
          "error",
        );
      }
    },
    [toast],
  );

  useEffect(() => {
    let cancelled = false;
    const activeSubscriptions = subscriptions.current;

    listTasks()
      .then((active) => {
        if (cancelled) return;
        active.forEach((task) => {
          applyTask(task);
          subscribe(task.task_id);
        });
      })
      .catch(() => {
        // Offline or API unavailable; live restore simply does not happen.
      });

    return () => {
      cancelled = true;
      activeSubscriptions.forEach((cleanup) => cleanup());
      activeSubscriptions.clear();
    };
  }, [applyTask, subscribe]);

  const tasks = useMemo(
    () =>
      Object.values(snapshot)
        .filter((task) => !isTerminal(task.status))
        .sort((a, b) => a.created_at.localeCompare(b.created_at)),
    [snapshot],
  );

  const value = useMemo<ActiveTasksValue>(
    () => ({ tasks, finishedTask, trackTask, cancelTask }),
    [tasks, finishedTask, trackTask, cancelTask],
  );

  return (
    <ActiveTasksContext.Provider value={value}>
      {children}
    </ActiveTasksContext.Provider>
  );
}
