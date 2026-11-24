import { useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";
import {
  getActivePlaylistTitle,
  subscribeActivePlaylistTitle,
  titleForPath,
} from "../navigation";
import UserMenu from "./UserMenu";

/** Material 3 top app bar. */
export default function TopAppBar() {
  const { pathname } = useLocation();
  const playlistTitle = useSyncExternalStore(
    subscribeActivePlaylistTitle,
    getActivePlaylistTitle,
    getActivePlaylistTitle,
  );

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 bg-surface px-4 sm:px-6">
      <img src="/favicon.svg" alt="" className="h-9 w-9 lg:hidden" />
      <h1 className="min-w-0 flex-1 truncate text-title-large text-on-surface">
        {titleForPath(pathname, playlistTitle)}
      </h1>
      <UserMenu />
    </header>
  );
}
