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

export function titleForPath(pathname: string): string {
  if (pathname === "/") return "Inici";
  if (pathname.startsWith("/library/playlist")) return "Llista de reproducció";
  if (pathname.startsWith("/library")) return "Biblioteca";
  if (pathname.startsWith("/history")) return "Historial";
  if (pathname.startsWith("/settings")) return "Configuració";
  if (pathname.startsWith("/admin")) return "Administració";
  return "Vidfetch";
}
