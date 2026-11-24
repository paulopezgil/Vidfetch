import { useEffect, useRef } from "react";
import { useToast } from "../components/Toast";
import { useDownloads } from "../downloads/DownloadsProvider";
import {
  QUOTA_EXCEEDED_MESSAGE,
  isAudioSelector,
  loadOfflineIndex,
  offlineMediaError,
  saveOfflineMedia,
} from "./media";

/**
 * Second phase of an audio download: transfer the finished media locally.
 *
 * The server job only produces a shared asset; this hook watches the existing
 * download poll for a job that becomes `ready` with an asset id and an audio
 * selector, then copies it into the offline cache once. Songs that were
 * already ready before this session stay cloud-only until the user taps their
 * offline control.
 *
 * Success is silent (the row switches to its check state); only failures
 * surface a toast, so a batch of songs does not flood the snackbar host.
 */
export default function AutoOfflineTransfer() {
  const { jobs, loading, error } = useDownloads();
  const toast = useToast();
  const initializedRef = useRef(false);
  const handledRef = useRef(new Set<string>());

  // Populate saved state before the first rows render.
  useEffect(() => {
    void loadOfflineIndex();
  }, []);

  useEffect(() => {
    if (loading) return;
    if (!initializedRef.current) {
      // Wait for a real server snapshot; an offline boot must not mistake the
      // old cloud library for fresh downloads.
      if (error && jobs.length === 0) return;
      initializedRef.current = true;
      for (const job of jobs) {
        if (job.status === "ready" && job.asset_id) {
          handledRef.current.add(job.asset_id);
        }
      }
      return;
    }

    for (const job of jobs) {
      const assetId = job.asset_id;
      if (job.status !== "ready" || !assetId) continue;
      if (!isAudioSelector(job.format_selector)) continue;
      if (handledRef.current.has(assetId)) continue;

      handledRef.current.add(assetId);
      void saveOfflineMedia(assetId).then((copied) => {
        if (copied) return;
        const quotaMessage = offlineMediaError(assetId);
        toast(
          quotaMessage === QUOTA_EXCEEDED_MESSAGE
            ? quotaMessage
            : `No s’ha pogut desar «${job.title}» per a escoltar sense connexió.`,
          "error",
        );
      });
    }
  }, [error, jobs, loading, toast]);

  return null;
}
