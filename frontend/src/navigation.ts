export interface Destination {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
}

/** Top-level destinations. Order is stable across every navigation form. */
export const destinations: Destination[] = [
  { to: "/", label: "Home", icon: "home", end: true },
  { to: "/tracks", label: "Tracks", icon: "library_music" },
  { to: "/playlists", label: "Playlists", icon: "queue_music" },
  { to: "/artists", label: "Artists & Albums", icon: "person" },
];

/** Admin-only destination, appended for accounts with `app_role = 'admin'`. */
export const adminDestination: Destination = {
  to: "/admin",
  label: "Admin",
  icon: "admin_panel_settings",
  end: true,
};

/** Destinations visible to the current account. */
export function destinationsFor(isAdmin: boolean): Destination[] {
  return isAdmin ? [...destinations, adminDestination] : destinations;
}

/*
 * The top app bar needs the human title of the playlist currently open. The
 * detail page publishes it here after loading, so `titleForPath` stays a pure
 * path function for every other destination.
 */
let activePlaylistTitle: string | null = null;
const titleListeners = new Set<() => void>();

export function setActivePlaylistTitle(title: string | null): void {
  const next = title?.trim() || null;
  if (next === activePlaylistTitle) return;
  activePlaylistTitle = next;
  titleListeners.forEach((listener) => listener());
}

export function subscribeActivePlaylistTitle(listener: () => void): () => void {
  titleListeners.add(listener);
  return () => {
    titleListeners.delete(listener);
  };
}

export function getActivePlaylistTitle(): string | null {
  return activePlaylistTitle;
}

export function titleForPath(
  pathname: string,
  playlistTitle: string | null = activePlaylistTitle,
): string {
  if (pathname === "/") return "Home";
  if (pathname === "/tracks") return "Tracks";
  if (pathname === "/playlists") return "Playlists";
  if (pathname.startsWith("/playlists/")) {
    return playlistTitle?.trim() || "Playlist";
  }
  if (pathname === "/artists") return "Artists & Albums";
  if (pathname.startsWith("/admin")) return "Administració";
  return "Vidfetch";
}
