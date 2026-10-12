import { useCallback, useEffect, useState } from "react";
import type { Health } from "../types";
import { getHealth } from "../api";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import Card from "../components/Card";
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
    <div className="flex items-center gap-3 p-4">
      <Icon
        name={ok ? "check_circle" : "cancel"}
        filled={ok}
        className={`text-[20px] ${ok ? "text-success" : "text-error"}`}
      />
      <span className="min-w-0 flex-1 text-body-large text-on-surface">
        {label}
      </span>
      <span className="text-body-medium text-on-surface-variant">
        {ok ? (version ?? "Available") : "Not available"}
      </span>
    </div>
  );
}

function Row({
  icon,
  label,
  value,
}: {
  icon: string;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3 p-4">
      <Icon name={icon} className="text-[20px] text-on-surface-variant" />
      <span className="min-w-0 flex-1 text-body-large text-on-surface">
        {label}
      </span>
      <span className="text-body-medium text-on-surface-variant">{value}</span>
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
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <section className="space-y-2">
        <h2 className="px-1 text-title-medium text-on-surface">Runtime</h2>
        <Card variant="outlined" className="overflow-hidden">
          {error ? (
            <div className="p-4">
              <ErrorBanner message={error} onRetry={load} />
            </div>
          ) : !health ? (
            <div className="flex items-center gap-3 p-4 text-body-medium text-on-surface-variant">
              <Spinner /> Checking dependencies…
            </div>
          ) : (
            <div className="divide-y divide-outline-variant">
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
              <Row
                icon="terminal"
                label="yt-dlp"
                value={health.ytdlp_version ?? "Unknown"}
              />
              <Row
                icon="deployed_code"
                label="Application"
                value={`v${health.version}`}
              />
            </div>
          )}
        </Card>
      </section>

      <section className="space-y-2">
        <h2 className="px-1 text-title-medium text-on-surface">
          Storage policy
        </h2>
        <Card
          variant="outlined"
          className="space-y-3 p-4 text-body-medium text-on-surface-variant"
        >
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
        </Card>
      </section>

      <section className="space-y-2">
        <h2 className="px-1 text-title-medium text-on-surface">About</h2>
        <Card variant="outlined" className="flex items-start gap-3 p-4">
          <Icon name="info" className="text-[20px] text-primary" />
          <p className="text-body-medium text-on-surface-variant">
            Downloads are performed with yt-dlp. Only download content you are
            authorised to download and ensure you comply with applicable laws,
            platform terms of service, and content rights.
          </p>
        </Card>
      </section>
    </div>
  );
}
