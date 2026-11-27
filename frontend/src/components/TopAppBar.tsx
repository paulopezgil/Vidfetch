import { useSyncExternalStore } from "react";
import { useLocation } from "react-router-dom";
import {
  getActivePlaylistTitle,
  subscribeActivePlaylistTitle,
  titleForPath,
} from "../navigation";
import UserMenu from "./UserMenu";
import Logo from "./Logo";

/** Material 3 top app bar. */
export default function TopAppBar() {
  const { pathname } = useLocation();
  const playlistTitle = useSyncExternalStore(
    subscribeActivePlaylistTitle,
    getActivePlaylistTitle,
    getActivePlaylistTitle,
  );

  return (
    <header className="flex min-h-16 shrink-0 items-center gap-3 bg-surface px-4 pt-[env(safe-area-inset-top)] sm:px-6">
      <Logo className="h-9 w-9 lg:hidden" />
      <h1 className="min-w-0 flex-1 truncate text-title-large text-on-surface">
        {titleForPath(pathname, playlistTitle)}
      </h1>
      <UserMenu />
    </header>
  );
}
