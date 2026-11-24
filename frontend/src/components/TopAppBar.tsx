import { useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";
import {
  getActivePlaylistTitle,
  subscribeActivePlaylistTitle,
  titleForPath,
} from "../navigation";
import { formatBytes } from "../lib";
import Icon from "./Icon";
import { useOfflineMedia } from "../offline/media";

/** Material 3 top app bar. */
export default function TopAppBar() {
  const { pathname } = useLocation();
  const playlistTitle = useSyncExternalStore(
    subscribeActivePlaylistTitle,
    getActivePlaylistTitle,
    getActivePlaylistTitle,
  );
  const offline = useOfflineMedia();
  const offlineLabel = `${offline.count} ${
    offline.count === 1 ? "cançó disponible" : "cançons disponibles"
  } sense connexió · ${formatBytes(offline.bytes)}`;

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 bg-surface px-4 sm:px-6">
      <img src="/favicon.svg" alt="" className="h-9 w-9 lg:hidden" />
      <h1 className="min-w-0 flex-1 truncate text-title-large text-on-surface">
        {titleForPath(pathname, playlistTitle)}
      </h1>
      {offline.count > 0 ? (
        <span
          title={offlineLabel}
          aria-label={offlineLabel}
          className="flex shrink-0 items-center gap-1 rounded-full bg-surface-container-high px-2.5 py-1 text-label-medium text-on-surface-variant"
        >
          <Icon name="offline_pin" className="text-[16px]" />
          <span className="tabular-nums">{offline.count}</span>
          <span aria-hidden="true">·</span>
          <span className="tabular-nums">{formatBytes(offline.bytes)}</span>
        </span>
      ) : null}
    </header>
  );
}
