import {
  Component,
  type CSSProperties,
  type ErrorInfo,
  type ReactNode,
} from "react";

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  error: Error | null;
}

/** Resolve the scheme set by the inline boot script, before app CSS may load. */
function prefersDark(): boolean {
  if (typeof document === "undefined") return false;
  const theme = document.documentElement.dataset.theme;
  if (theme === "dark") return true;
  if (theme === "light") return false;
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function recoveryStyles(dark: boolean): {
  shell: CSSProperties;
  card: CSSProperties;
  title: CSSProperties;
  body: CSSProperties;
  button: CSSProperties;
  detail: CSSProperties;
} {
  const surface = dark ? "#0f0f0f" : "#f9f9f9";
  const onSurface = dark ? "#e3e3e3" : "#1b1b1b";
  const surfaceContainer = dark ? "#1f1f1f" : "#f3f3f3";
  const outline = dark ? "#444746" : "#c6c6c6";
  const muted = dark ? "#c6c6c6" : "#474747";
  const primary = dark ? "#dc362e" : "#c00100";

  return {
    shell: {
      minHeight: "100vh",
      boxSizing: "border-box",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
      background: surface,
      color: onSurface,
      colorScheme: dark ? "dark" : "light",
      fontFamily:
        'Roboto, system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    },
    card: {
      width: "100%",
      maxWidth: "440px",
      boxSizing: "border-box",
      background: surfaceContainer,
      border: `1px solid ${outline}`,
      borderRadius: "16px",
      padding: "24px",
      boxShadow: dark
        ? "0 4px 16px rgba(0, 0, 0, 0.45)"
        : "0 4px 16px rgba(0, 0, 0, 0.12)",
    },
    title: {
      margin: 0,
      fontSize: "22px",
      fontWeight: 500,
      lineHeight: 1.35,
    },
    body: {
      margin: "8px 0 0",
      fontSize: "14px",
      lineHeight: 1.55,
      color: muted,
    },
    button: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      marginTop: "20px",
      border: 0,
      borderRadius: "999px",
      padding: "10px 22px",
      background: primary,
      color: "#ffffff",
      font: "inherit",
      fontWeight: 500,
      cursor: "pointer",
    },
    detail: {
      margin: "16px 0 0",
      maxHeight: "160px",
      overflow: "auto",
      padding: "12px",
      border: `1px solid ${outline}`,
      borderRadius: "8px",
      background: surface,
      color: muted,
      fontFamily:
        'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
      fontSize: "12px",
      lineHeight: 1.5,
      whiteSpace: "pre-wrap",
      overflowWrap: "anywhere",
    },
  };
}

/**
 * Last-resort React recovery screen.
 *
 * Everything is inline so it still renders when the application stylesheet is
 * the thing that failed. The boot fallback in `index.html` covers failures
 * before React can mount; this boundary covers render and lifecycle errors.
 */
export default class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Vidfetch: unhandled render error", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const styles = recoveryStyles(prefersDark());
    const message = error.message?.trim() || "Error desconegut";

    return (
      <div role="alert" style={styles.shell}>
        <div style={styles.card}>
          <h1 style={styles.title}>No s’ha pogut carregar l’aplicació</h1>
          <p style={styles.body}>
            Hi ha hagut un error inesperat en iniciar Vidfetch. Recarrega la
            pàgina per tornar-ho a provar.
          </p>
          <button
            type="button"
            style={styles.button}
            onClick={() => window.location.reload()}
          >
            Recarrega
          </button>
          <pre style={styles.detail}>{message}</pre>
        </div>
      </div>
    );
  }
}
