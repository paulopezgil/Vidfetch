import { useState } from "react";
import Icon from "./Icon";
import IconButton from "./IconButton";
import Spinner from "./Spinner";
import { useToast } from "./Toast";
import {
  removeOfflineMedia,
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

/**
 * One offline-state control per song.
 *
 * - cloud icon: the song lives on the server only; tap to copy it locally.
 * - spinner: a copy is being transferred; the control is disabled.
 * - filled check: the song is available offline; tap to free the space.
 *
 * The control derives everything from `assetId`, so it also works on rows that
 * never fetched a media token. Dark and light schemes both use the tonal
 * icon-button roles; the state is carried by icon *shape*, not color alone.
 */
export default function OfflineButton({
  assetId,
  title,
  size = "sm",
  className = "",
}: OfflineButtonProps) {
  const status = useOfflineMedia();
  const toast = useToast();
  const [removing, setRemoving] = useState(false);

  if (!assetId) return null;

  const saved = status.saved.has(assetId);
  const saving = status.saving.has(assetId) || removing;

  async function handleClick() {
    if (!assetId || saving) return;

    if (saved) {
      setRemoving(true);
      try {
        const removed = await removeOfflineMedia(assetId);
        if (!removed) {
          toast("No s’ha pogut alliberar el track del dispositiu.", "error");
        }
      } finally {
        setRemoving(false);
      }
      return;
    }

    const copied = await saveOfflineMedia(assetId);
    if (!copied) {
      toast(
        title
          ? `No s’ha pogut desar «${title}» per a escoltar sense connexió.`
          : "No s’ha pogut desar el track per a escoltar sense connexió.",
        "error",
      );
    }
  }

  const label = saving
    ? "S’està desant per a escoltar sense connexió"
    : saved
      ? "Disponible sense connexió"
      : "Desa per a escoltar sense connexió";
  const hint = saved
    ? "Disponible sense connexió · Toca per alliberar l’espai"
    : label;

  return (
    <IconButton
      variant="tonal"
      size={size}
      className={className}
      label={label}
      title={hint}
      ariaPressed={saved}
      disabled={saving}
      onClick={() => void handleClick()}
    >
      {saving ? (
        <Spinner className="text-[20px]" />
      ) : (
        <Icon
          name={saved ? "check_circle" : "cloud_download"}
          filled={saved}
          className="text-[20px]"
        />
      )}
    </IconButton>
  );
}
