import { useCallback, useState } from "react";
import type { FormatName, InfoResult, OperationType } from "../types";
import type { MediaInfo } from "../types/v2";
import { getInfo } from "../lib/api";
import UrlInput from "../components/UrlInput";
import InfoPreview from "../components/InfoPreview";
import JobCard from "../components/JobCard";
import EmptyState from "../components/EmptyState";
import Spinner from "../components/Spinner";
import { useToast } from "../components/Toast";
import { useDownloads } from "../downloads/DownloadsProvider";

/** Adapt the v2 `MediaInfo` payload to the shape `InfoPreview` renders. */
function toInfoResult(info: MediaInfo): InfoResult {
  return {
    type: info.type,
    id: info.id,
    title: info.title,
    channel: info.channel,
    thumbnail: info.thumbnail,
    duration: info.duration,
    formats: info.formats,
    video_count: info.video_count,
    entries: info.entries,
    ext: info.ext,
    webpage_url: info.webpage_url,
  };
}

/** Correlation key so the backend can deduplicate replayed create requests. */
function newIdempotencyKey(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `dl-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

export default function Dashboard() {
  const toast = useToast();
  const { activeJobs, createJob, cancelJob } = useDownloads();
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
      const result = await getInfo(url);
      setInfo(toInfoResult(result));
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
        await createJob({
          url: submittedUrl,
          kind: opts.operation_type === "playlist" ? "playlist" : "video",
          format: opts.format,
          embed_subs: opts.embed_subs,
          idempotency_key: newIdempotencyKey(),
        });
        toast("Descàrrega iniciada", "info");
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "No s’ha pogut iniciar la descàrrega",
          "error",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [submittedUrl, createJob, toast],
  );

  const handleCancel = useCallback(
    async (jobId: string) => {
      try {
        await cancelJob(jobId);
      } catch (e) {
        toast(
          e instanceof Error ? e.message : "No s’ha pogut cancel·lar la descàrrega",
          "error",
        );
      }
    },
    [cancelJob, toast],
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
        {activeJobs.length > 0 ? (
          <div className="space-y-3">
            {activeJobs.map((job) => (
              <JobCard key={job.id} job={job} onCancel={handleCancel} />
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
