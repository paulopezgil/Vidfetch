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
  { to: "/history", label: "Historial", icon: "history" },
  { to: "/settings", label: "Configuració", icon: "settings" },
];

export function titleForPath(pathname: string): string {
  if (pathname === "/") return "Inici";
  if (pathname.startsWith("/library/playlist")) return "Llista de reproducció";
  if (pathname.startsWith("/library")) return "Biblioteca";
  if (pathname.startsWith("/history")) return "Historial";
  if (pathname.startsWith("/settings")) return "Configuració";
  return "Vidfetch";
}
