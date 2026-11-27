export interface Destination {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
}

/** Top-level destinations. Order is stable across every navigation form. */
export const destinations: Destination[] = [
  { to: "/", label: "Inici", icon: "home", end: true },
  { to: "/library", label: "Biblioteca", icon: "video_library" },
  { to: "/playlists", label: "Llistes", icon: "queue_music" },
  { to: "/settings", label: "Configuració", icon: "settings" },
  { to: "/help", label: "Ajuda", icon: "help" },
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
 * The top app bar needs the human title of the playlist currently open
 * (curated or imported). The detail pages publish it here after loading, so
 * `titleForPath` stays a pure path function for every other destination.
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
  if (pathname === "/") return "Inici";
  // One library with four sections behind a single destination.
  if (pathname === "/library" || pathname.startsWith("/library/")) {
    return "Biblioteca";
  }
  // Compatibility for bookmarks and redirects that still use the old paths;
  // the router replaces them with the matching `/library/<section>` route.
  if (
    pathname === "/songs" ||
    pathname === "/videos" ||
    pathname === "/artists" ||
    pathname === "/tracks"
  ) {
    return "Biblioteca";
  }
  if (pathname === "/playlists") return "Llistes";
  if (pathname.startsWith("/playlists/") && /\/add\/?$/.test(pathname)) {
    return "Afegeix cançons";
  }
  if (pathname.startsWith("/playlists/")) {
    return playlistTitle?.trim() || "Llista";
  }
  if (pathname.startsWith("/imported/")) {
    return playlistTitle?.trim() || "Llista importada";
  }
  // `/install` is kept as a redirect for old bookmarks and links.
  if (pathname === "/help" || pathname === "/install") return "Ajuda";
  if (pathname === "/settings") return "Configuració";
  if (pathname.startsWith("/admin")) return "Administració";
  return "Vidfetch";
}
