import { useEffect, useId, useRef, useState } from "react";
import { formatBytes } from "../lib";
import {
  estimateOfflineUsage,
  useOfflineMedia,
} from "../offline/media";
import {
  readStorageEstimate,
  refreshPersistenceState,
  type StorageEstimate,
} from "../offline/storage";
import { useOfflineStatus, type PersistenceState } from "../offline/status";
import Button from "./Button";
import Icon from "./Icon";
import IconButton from "./IconButton";

interface StorageDialogProps {
  open: boolean;
  onClose: () => void;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Read-only overview of the offline media store.
 *
 * Saved songs are permanent: this dialog only reports how many copies exist,
 * how much space they and the app use, and whether the browser granted
 * persistent storage. It deliberately exposes no removal action.
 */
export default function StorageDialog({ open, onClose }: StorageDialogProps) {
  const titleId = useId();
  const media = useOfflineMedia();
  const { persistence } = useOfflineStatus();
  const [estimate, setEstimate] = useState<StorageEstimate | null>(null);
  const [checking, setChecking] = useState(false);

  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Refresh the saved index and storage numbers each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setChecking(true);

    void Promise.allSettled([
      estimateOfflineUsage(),
      readStorageEstimate(),
      refreshPersistenceState(),
    ]).then(([, usage]) => {
      if (cancelled) return;
      setEstimate(usage.status === "fulfilled" ? usage.value : null);
      setChecking(false);
    });

    return () => {
      cancelled = true;
    };
  }, [open]);

  // Escape closes, Tab stays inside, and focus returns to the chip on close.
  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    });

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable =
        dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      restoreRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const persistenceCopy: Record<
    PersistenceState,
    { label: string; hint: string; icon: string }
  > = {
    granted: {
      label: "Concedit",
      hint: "El navegador conserva aquest espai encara que el dispositiu vagi just.",
      icon: "verified_user",
    },
    denied: {
      label: "No concedit",
      hint: "El navegador no ha confirmat que conservi aquest espai.",
      icon: "info",
    },
    unsupported: {
      label: "No compatible",
      hint: "Aquest navegador no ofereix emmagatzematge persistent.",
      icon: "block",
    },
    unknown: {
      label: "S’està comprovant…",
      hint: "Encara no s’ha pogut comprovar l’estat.",
      icon: "hourglass_top",
    },
  };
  const persistenceState = persistenceCopy[persistence];
  const songLabel = media.count === 1 ? "cançó" : "cançons";

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-scrim/32 p-0 sm:items-center sm:p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={checking}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-[520px] rounded-t-xl bg-surface-container-high text-on-surface shadow-elevation-3 focus:outline-none sm:rounded-xl"
      >
        <div className="flex items-start gap-2 px-6 pb-2 pt-5">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-headline-small">
              Emmagatzematge sense connexió
            </h2>
            <p className="mt-1 text-body-medium text-on-surface-variant">
              Les cançons desades es conserven al dispositiu per escoltar-les
              sense connexió.
            </p>
          </div>
          <IconButton label="Tanca" onClick={onClose}>
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>

        <div className="space-y-5 px-6 pb-2 pt-4">
          <dl className="divide-y divide-outline-variant rounded-md bg-surface-container px-4">
            <div className="flex items-center gap-3 py-3">
              <dt className="min-w-0 flex-1 text-body-medium text-on-surface-variant">
                Cançons desades
              </dt>
              <dd className="text-title-small tabular-nums text-on-surface">
                {media.count} {songLabel}
              </dd>
            </div>
            <div className="flex items-center gap-3 py-3">
              <dt className="min-w-0 flex-1 text-body-medium text-on-surface-variant">
                Espai de les cançons
              </dt>
              <dd className="text-title-small tabular-nums text-on-surface">
                {formatBytes(media.bytes)}
              </dd>
            </div>
            <div className="flex items-center gap-3 py-3">
              <dt className="min-w-0 flex-1 text-body-medium text-on-surface-variant">
                Ús total del navegador
              </dt>
              <dd className="text-title-small tabular-nums text-on-surface">
                {checking && !estimate
                  ? "S’està calculant…"
                  : estimate
                    ? `${formatBytes(estimate.usage)} de ${formatBytes(
                        estimate.quota,
                      )}`
                    : "No disponible"}
              </dd>
            </div>
          </dl>

          <div className="flex items-start gap-3 rounded-md bg-surface-container px-4 py-3">
            <Icon
              name={persistenceState.icon}
              className="mt-0.5 text-[20px] text-on-surface-variant"
            />
            <div className="min-w-0 flex-1">
              <p className="text-title-small text-on-surface">
                Emmagatzematge persistent: {persistenceState.label}
              </p>
              <p className="mt-0.5 text-body-small text-on-surface-variant">
                {persistenceState.hint}
              </p>
            </div>
          </div>
        </div>

        <div className="flex justify-end px-6 pb-5 pt-3">
          <Button variant="text" onClick={onClose}>
            Tanca
          </Button>
        </div>
      </div>
    </div>
  );
}
