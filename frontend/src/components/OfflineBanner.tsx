import { useEffect, useState } from "react";
import { refreshPendingCount, useOfflineStatus } from "../offline/status";
import { flushQueue } from "../offline/sync";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";

/**
 * Subtle Material 3 banner under the top app bar.
 *
 * It reports the connection state, the number of edits waiting to be replayed
 * and the flush lifecycle. It is only dismissible while online: an offline
 * banner always stays visible so the cached state is never silent.
 */
export default function OfflineBanner() {
  const status = useOfflineStatus();
  const [dismissed, setDismissed] = useState<string | null>(null);

  useEffect(() => {
    void refreshPendingCount();
  }, []);

  useEffect(() => {
    const onOnline = () => {
      void flushQueue();
    };
    window.addEventListener("online", onOnline);
    if (typeof navigator === "undefined" || navigator.onLine) {
      // Covers a reload with queued edits: the profile bootstrap also flushes,
      // but the shared flush guard makes the duplicate safe.
      void flushQueue();
    }
    return () => window.removeEventListener("online", onOnline);
  }, []);

  // An offline banner can never be dismissed; a dismissal only hides the
  // current online state (and is forgotten as soon as that state changes).
  useEffect(() => {
    if (!status.online) setDismissed(null);
  }, [status.online]);

  const pendingLabel = `${status.pending} ${
    status.pending === 1 ? "canvi pendent" : "canvis pendents"
  }`;
  const signature = `${status.online}|${status.pending}|${status.syncing}`;

  const visible = !status.online || status.pending > 0 || status.syncing;
  if (!visible) return null;
  if (status.online && dismissed === signature) return null;

  const message = status.syncing
    ? "S’està sincronitzant…"
    : !status.online
      ? status.usingCache
        ? "Sense connexió · dades desades"
        : "Sense connexió"
      : pendingLabel;

  return (
    <div
      role="status"
      aria-live="polite"
      title={status.lastError ?? undefined}
      className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-outline-variant bg-surface-container-high px-4 py-1.5 text-on-surface-variant sm:px-6"
    >
      {status.syncing ? (
        <Spinner className="text-[18px]" />
      ) : (
        <Icon
          name={status.online ? "cloud_upload" : "cloud_off"}
          className="text-[18px]"
        />
      )}

      <p className="min-w-0 flex-1 truncate text-body-medium">{message}</p>

      {!status.syncing && status.pending > 0 ? (
        <span className="rounded-full bg-on-surface/8 px-2 py-0.5 text-label-medium">
          {pendingLabel}
        </span>
      ) : null}

      {status.syncing ? null : (
        <Button
          variant="text"
          size="sm"
          onClick={() => void flushQueue()}
          className="shrink-0"
        >
          <Icon name="sync" className="text-[18px]" />
          {status.pending > 0 ? "Sincronitza" : "Torna-ho a provar"}
        </Button>
      )}

      {status.online && !status.syncing ? (
        <IconButton
          label="Amaga l’avís"
          size="sm"
          className="-mr-2"
          onClick={() => setDismissed(signature)}
        >
          <Icon name="close" className="text-[18px]" />
        </IconButton>
      ) : null}
    </div>
  );
}
