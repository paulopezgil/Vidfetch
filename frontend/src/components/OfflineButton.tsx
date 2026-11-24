import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import { useToast } from "./Toast";
import {
  QUOTA_EXCEEDED_MESSAGE,
  offlineMediaError,
  saveOfflineMedia,
  useOfflineMedia,
} from "../offline/media";

interface OfflineButtonProps {
  /** The asset whose local copy this control manages. */
  assetId: string | null | undefined;
  /** Track title used in failure messages. */
  title?: string;
  size?: "sm" | "md";
  className?: string;
}

const sizeClasses: Record<"sm" | "md", string> = {
  sm: "h-10 w-10",
  md: "h-12 w-12",
};

/**
 * One offline-state control per song.
 *
 * - cloud icon: the song lives on the server only; tap to copy it locally.
 * - spinner: a copy is being transferred; the control is not interactive.
 * - filled check: the song is available offline. Saved songs are permanent, so
 *   this state is a non-interactive status indicator, not a button.
 *
 * The compact indicator uses the same tonal icon-button container as the save
 * action, but it is a `<span role="img">` with an accessible name: there is no
 * click handler and no keyboard stop. Dark and light schemes both use the
 * tonal container roles; the state is carried by icon shape, not color alone.
 */
export default function OfflineButton({
  assetId,
  title,
  size = "sm",
  className = "",
}: OfflineButtonProps) {
  const status = useOfflineMedia();
  const toast = useToast();

  if (!assetId) return null;

  const saved = status.saved.has(assetId);
  const saving = status.saving.has(assetId);

  async function handleSave() {
    if (!assetId || saving || saved) return;

    const copied = await saveOfflineMedia(assetId);
    if (copied) return;

    const quotaMessage = offlineMediaError(assetId);
    if (quotaMessage === QUOTA_EXCEEDED_MESSAGE) {
      toast(quotaMessage, "error");
      return;
    }
    toast(
      title
        ? `No s’ha pogut desar «${title}» per a escoltar sense connexió.`
        : "No s’ha pogut desar el track per a escoltar sense connexió.",
      "error",
    );
  }

  if (saved) {
    return (
      <span
        role="img"
        aria-label="Disponible sense connexió"
        title="Disponible sense connexió"
        className={`inline-flex shrink-0 items-center justify-center rounded-full bg-secondary-container text-on-secondary-container ${sizeClasses[size]} ${className}`}
      >
        <Icon name="check_circle" filled className="text-[20px]" />
      </span>
    );
  }

  if (saving) {
    return (
      <span
        role="img"
        aria-label="S’està desant per a escoltar sense connexió"
        title="S’està desant per a escoltar sense connexió"
        className={`inline-flex shrink-0 items-center justify-center rounded-full bg-secondary-container text-on-secondary-container ${sizeClasses[size]} ${className}`}
      >
        <Spinner className="text-[20px]" />
      </span>
    );
  }

  return (
    <IconButton
      variant="tonal"
      size={size}
      className={className}
      label="Desa per a escoltar sense connexió"
      title="Desa per a escoltar sense connexió"
      onClick={() => void handleSave()}
    >
      <Icon name="cloud_download" className="text-[20px]" />
    </IconButton>
  );
}
