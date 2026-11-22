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
import type { CreateDownloadPayload, DownloadJob } from "../types/v2";
import { isActiveJob } from "../types/v2";
import { cancelDownload, createDownload, listDownloads } from "../lib/api";

/** Fast cadence while at least one job is queued or running. */
const POLL_ACTIVE_MS = 1500;
/** Slow cadence once every job has reached a terminal state. */
const POLL_IDLE_MS = 10_000;
/** Upper bound of jobs held in memory for the dashboard/history views. */
const JOB_LIMIT = 100;

export interface DownloadsValue {
  /** Jobs as returned by the API, newest first. */
  jobs: DownloadJob[];
  /** Jobs that are still queued or running. */
  activeJobs: DownloadJob[];
  /** Jobs that reached `ready`, `failed` or `cancelled`. */
  finishedJobs: DownloadJob[];
  /** True until the first list response (or error) arrives. */
  loading: boolean;
  /** Last polling error; cleared by the next successful refresh. */
  error: string | null;
  /** Fetch the list immediately and reschedule the poll timer. */
  refresh: () => Promise<void>;
  /** Create a job and insert it into the list immediately. */
  createJob: (payload: CreateDownloadPayload) => Promise<DownloadJob>;
  /** Cancel a job, update it in place, then refresh the list. */
  cancelJob: (jobId: string) => Promise<DownloadJob>;
}

const DownloadsContext = createContext<DownloadsValue | null>(null);

export function useDownloads(): DownloadsValue {
  const value = useContext(DownloadsContext);
  if (!value) {
    throw new Error("useDownloads must be used inside <DownloadsProvider>");
  }
  return value;
}

function messageOf(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "No s’han pogut carregar les descàrregues.";
}

/**
 * Owns the v2 download-job list for the whole app.
 *
 * The v2 contract is polling (no SSE): one timer at a time, no overlapping
 * requests, 1.5 s while a job is active and 10 s when everything is terminal.
 * Polling pauses while the document is hidden and resumes on visibility.
 */
export function DownloadsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const jobsRef = useRef<DownloadJob[]>([]);
  const mountedRef = useRef(false);
  const inFlightRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const tickRef = useRef<() => void>(() => {});

  const applyJobs = useCallback((next: DownloadJob[]) => {
    jobsRef.current = next;
    setJobs(next);
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const schedule = useCallback(() => {
    clearTimer();
    if (!mountedRef.current || document.hidden) return;
    const hasActive = jobsRef.current.some((job) => isActiveJob(job.status));
    timerRef.current = window.setTimeout(
      () => tickRef.current(),
      hasActive ? POLL_ACTIVE_MS : POLL_IDLE_MS,
    );
  }, [clearTimer]);

  const tick = useCallback(async () => {
    if (!mountedRef.current) return;
    clearTimer();
    // Never overlap requests; the in-flight call reschedules when it settles.
    if (document.hidden || inFlightRef.current) return;

    inFlightRef.current = true;
    try {
      const page = await listDownloads({ limit: JOB_LIMIT });
      if (!mountedRef.current) return;
      applyJobs(page.items);
      setError(null);
    } catch (e) {
      if (mountedRef.current) setError(messageOf(e));
    } finally {
      inFlightRef.current = false;
      if (mountedRef.current) {
        setLoading(false);
        schedule();
      }
    }
  }, [applyJobs, clearTimer, schedule]);

  useEffect(() => {
    tickRef.current = () => {
      void tick();
    };
  }, [tick]);

  useEffect(() => {
    mountedRef.current = true;
    void tick();

    const onVisibilityChange = () => {
      if (document.hidden) {
        clearTimer();
      } else {
        // Refresh straight away so a returning tab shows current progress.
        void tick();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      mountedRef.current = false;
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [tick, clearTimer]);

  const refresh = useCallback(async () => {
    await tick();
  }, [tick]);

  const createJob = useCallback(
    async (payload: CreateDownloadPayload): Promise<DownloadJob> => {
      const job = await createDownload(payload);
      if (mountedRef.current) {
        const next = [
          job,
          ...jobsRef.current.filter((item) => item.id !== job.id),
        ];
        applyJobs(next);
        setError(null);
        setLoading(false);
        schedule();
      }
      return job;
    },
    [applyJobs, schedule],
  );

  const cancelJob = useCallback(
    async (jobId: string): Promise<DownloadJob> => {
      const updated = await cancelDownload(jobId);
      if (mountedRef.current) {
        const next = jobsRef.current.map((item) =>
          item.id === updated.id ? updated : item,
        );
        const known = next.some((item) => item.id === updated.id);
        applyJobs(known ? next : [updated, ...next]);
        setError(null);
        schedule();
      }
      await tick();
      return updated;
    },
    [applyJobs, schedule, tick],
  );

  const activeJobs = useMemo(
    () => jobs.filter((job) => isActiveJob(job.status)),
    [jobs],
  );
  const finishedJobs = useMemo(
    () => jobs.filter((job) => !isActiveJob(job.status)),
    [jobs],
  );

  const value = useMemo<DownloadsValue>(
    () => ({
      jobs,
      activeJobs,
      finishedJobs,
      loading,
      error,
      refresh,
      createJob,
      cancelJob,
    }),
    [
      jobs,
      activeJobs,
      finishedJobs,
      loading,
      error,
      refresh,
      createJob,
      cancelJob,
    ],
  );

  return (
    <DownloadsContext.Provider value={value}>
      {children}
    </DownloadsContext.Provider>
  );
}
