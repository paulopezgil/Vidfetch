import { useEffect, useId, useRef } from "react";
import { useImageCache } from "../offline/images";
import IconButton from "./IconButton";
import Icon from "./Icon";

interface MediaPreviewDialogProps {
  open: boolean;
  title: string;
  /** Image source of an imported playlist item. */
  src: string;
  onClose: () => void;
}

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Material 3 basic dialog for previewing an image inline. Reuses the
 * predictable focus management (trapped Tab, Escape to close, focus
 * restoration) of ConfirmDialog.
 *
 * Audio and video deliberately do not use a dialog: they play in the
 * persistent now-playing player instead.
 */
export default function MediaPreviewDialog({
  open,
  title,
  src,
  onClose,
}: MediaPreviewDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  useImageCache(open ? src : null);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement as HTMLElement | null;

    function onKey(event: KeyboardEvent) {
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

    window.addEventListener("keydown", onKey);
    dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim/32 p-4"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="flex w-full max-w-3xl flex-col rounded-xl bg-surface-container-high text-on-surface shadow-elevation-3 focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-2 p-4 pb-2 sm:p-6 sm:pb-3">
          <h2
            id={titleId}
            className="min-w-0 flex-1 text-title-large text-on-surface"
          >
            {title}
          </h2>
          <IconButton label="Tanca" onClick={onClose}>
            <Icon name="close" className="text-[20px]" />
          </IconButton>
        </div>

        <div className="flex max-h-[70vh] items-center justify-center overflow-hidden px-4 pb-4 sm:px-6 sm:pb-6">
          <img
            src={src}
            alt={title}
            className="max-h-[70vh] max-w-full object-contain"
          />
        </div>
      </div>
    </div>
  );
}
