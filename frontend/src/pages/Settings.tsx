import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, XCircle, Info } from "lucide-react";
import type { Health } from "../types";
import { getHealth } from "../api";
import ErrorBanner from "../components/ErrorBanner";
import Spinner from "../components/Spinner";

function Dep({
  ok,
  label,
  version,
}: {
  ok: boolean;
  label: string;
  version?: string | null;
}) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 py-3 last:border-0">
      <div className="flex items-center gap-2.5">
        {ok ? (
          <CheckCircle2 className="h-4 w-4 text-success" />
        ) : (
          <XCircle className="h-4 w-4 text-danger" />
        )}
        <span className="text-sm text-fg">{label}</span>
      </div>
      <span className="text-sm text-fg-secondary">
        {ok ? version ?? "Available" : "Not available"}
      </span>
    </div>
  );
}

export default function Settings() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHealth(await getHealth());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the server.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6 px-4 py-6 sm:px-6">
      <header>
        <h1 className="text-xl font-semibold text-fg">Settings</h1>
        <p className="mt-1 text-sm text-fg-secondary">
          Runtime status and storage policy.
        </p>
      </header>

      <section className="card p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-secondary">
          Runtime
        </h2>
        {error ? (
          <div className="mt-3">
            <ErrorBanner message={error} onRetry={load} />
          </div>
        ) : !health ? (
          <div className="mt-3 flex items-center gap-2 text-sm text-fg-secondary">
            <Spinner /> Checking dependencies…
          </div>
        ) : (
          <div className="mt-2 divide-y divide-line/60">
            <Dep
              ok={health.dependencies.ffmpeg_available}
              label="FFmpeg"
              version={health.dependencies.ffmpeg_version}
            />
            <Dep
              ok={health.dependencies.node_available}
              label="Node.js"
              version={health.dependencies.node_version}
            />
            <div className="flex items-center justify-between py-3">
              <span className="text-sm text-fg">yt-dlp</span>
              <span className="text-sm text-fg-secondary">
                {health.ytdlp_version ?? "Unknown"}
              </span>
            </div>
            <div className="flex items-center justify-between py-3">
              <span className="text-sm text-fg">Application</span>
              <span className="text-sm text-fg-secondary">
                v{health.version}
              </span>
            </div>
          </div>
        )}
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-secondary">
          Storage policy
        </h2>
        <div className="mt-3 space-y-3 text-sm text-fg-secondary">
          <p>
            When you download a full playlist, each video is saved as an
            individual file <em>and</em> packaged into a single ZIP archive.
            Both the files and the archive remain in your library, so you can
            grab a single video or the whole playlist as you prefer.
          </p>
          <p>
            Deleting a file removes it from disk but keeps its history record.
            Files deleted from a playlist can be re-downloaded at any time.
          </p>
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-secondary">
          About
        </h2>
        <div className="mt-3 flex items-start gap-2.5 text-sm text-fg-secondary">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" />
          <p>
            Downloads are performed with yt-dlp. Only download content you are
            authorised to download and ensure you comply with applicable laws,
            platform terms of service, and content rights.
          </p>
        </div>
      </section>
    </div>
  );
}
