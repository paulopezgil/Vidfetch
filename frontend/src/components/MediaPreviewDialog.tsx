import { useEffect, useRef } from "react";
import IconButton from "./IconButton";
import Icon from "./Icon";

interface MediaPreviewDialogProps {
  open: boolean;
  title: string;
  mediaType: "video" | "audio" | "image";
  src: string;
  onClose: () => void;
}

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Material 3 basic dialog for previewing media inline. Reuses the predictable
 * focus management (trapped Tab, Escape to close, focus restoration) of
 * ConfirmDialog.
 */
export default function MediaPreviewDialog({
  open,
  title,
  mediaType,
  src,
  onClose,
}: MediaPreviewDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
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

    window.addEventListener("keydown", onKey);
    dialogRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim/32 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="flex w-full max-w-3xl flex-col rounded-xl bg-surface-container-high text-on-surface shadow-elevation-3 focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-2 p-4 pb-2 sm:p-6 sm:pb-3">
          <h2 className="min-w-0 flex-1 text-title-large text-on-surface">
            {title}
          </h2>
          <IconButton label="Tanca" onClick={onClose}>
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>

        <div className="flex max-h-[70vh] items-center justify-center overflow-hidden px-4 pb-4 sm:px-6 sm:pb-6">
          {mediaType === "video" ? (
            <video
              controls
              autoPlay
              playsInline
              src={src}
              className="max-h-[70vh] w-full rounded-lg bg-black"
            >
              El vostre navegador no pot reproduir aquest vídeo.
            </video>
          ) : mediaType === "audio" ? (
            <audio controls autoPlay src={src} className="w-full">
              El vostre navegador no pot reproduir aquest àudio.
            </audio>
          ) : (
            <img
              src={src}
              alt={title}
              className="max-h-[70vh] max-w-full object-contain"
            />
          )}
        </div>
      </div>
    </div>
  );
}
