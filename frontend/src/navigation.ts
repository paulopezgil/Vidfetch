export interface Destination {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
}

/** Top-level destinations. Order is stable across every navigation form. */
export const destinations: Destination[] = [
  { to: "/", label: "Home", icon: "home", end: true },
  { to: "/library", label: "Library", icon: "video_library" },
  { to: "/history", label: "History", icon: "history" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

export function titleForPath(pathname: string): string {
  if (pathname === "/") return "Home";
  if (pathname.startsWith("/library/playlist")) return "Playlist";
  if (pathname.startsWith("/library")) return "Library";
  if (pathname.startsWith("/history")) return "History";
  if (pathname.startsWith("/settings")) return "Settings";
  return "Vidfetch";
}
