import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import AppErrorBoundary from "./components/AppErrorBoundary";
import { ThemeProvider } from "./theme/ThemeProvider";
import { prefetchOfflineFonts } from "./offline/fonts";
import "./index.css";

// The offline app shell is production-only: a service worker in dev would
// cache the HMR graph and serve stale modules. Font warming runs after load so
// it never delays the first paint.
if (import.meta.env.PROD) {
  window.addEventListener("load", () => {
    void prefetchOfflineFonts();
    if ("serviceWorker" in navigator) {
      void navigator.serviceWorker.register("/sw.js").catch(() => {
        // Progressive enhancement: a failed registration keeps the app online.
      });
    }
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
);
