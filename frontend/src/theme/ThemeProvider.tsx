import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/** User preference: follow the device, or force one scheme. */
export type ThemeMode = "system" | "light" | "dark";

/** Scheme actually applied to the document. */
export type ResolvedTheme = "light" | "dark";

/** Local storage key shared with the inline head script in `index.html`. */
export const THEME_STORAGE_KEY = "vidfetch.theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Browser chrome color per scheme, matching `--md-surface`. */
const THEME_COLORS: Record<ResolvedTheme, string> = {
  light: "#f9f9f9",
  dark: "#0f0f0f",
};

interface ThemeContextValue {
  /** Stored preference. */
  mode: ThemeMode;
  /** Scheme currently applied (`light`/`dark`, never `system`). */
  resolvedTheme: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredMode(): ThemeMode {
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return raw === "light" || raw === "dark" || raw === "system" ? raw : "system";
  } catch {
    return "system";
  }
}

function readSystemTheme(): ResolvedTheme {
  if (
    typeof window.matchMedia === "function" &&
    window.matchMedia(DARK_QUERY).matches
  ) {
    return "dark";
  }
  return "light";
}

function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  // Set inline as well: the stylesheet may not have parsed yet on first paint.
  root.style.colorScheme = theme;
  const meta = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  if (meta) meta.content = THEME_COLORS[theme];
}

/**
 * Appearance provider: stores the `system|light|dark` preference and applies
 * the resolved scheme to `<html data-theme>` plus the `theme-color` meta tag.
 *
 * `system` keeps a `matchMedia` listener alive, so a device switching to dark
 * mode updates the app without a reload. `index.html` runs the same resolution
 * inline before paint to avoid a flash of the wrong scheme.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(readSystemTheme);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? "dark" : "light");
    };
    query.addEventListener("change", onChange);
    setSystemTheme(query.matches ? "dark" : "light");
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);

  const resolvedTheme: ResolvedTheme = mode === "system" ? systemTheme : mode;

  useEffect(() => {
    applyTheme(resolvedTheme);
  }, [resolvedTheme]);

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage blocked: the choice still applies for this tab.
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ mode, resolvedTheme, setMode }),
    [mode, resolvedTheme, setMode],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) {
    throw new Error("useTheme must be used inside <ThemeProvider>");
  }
  return value;
}
