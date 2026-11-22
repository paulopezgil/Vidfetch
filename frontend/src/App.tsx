import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { DownloadsProvider } from "./downloads/DownloadsProvider";
import TopAppBar from "./components/TopAppBar";
import NavigationDrawer from "./components/NavigationDrawer";
import NavigationRail from "./components/NavigationRail";
import NavigationBar from "./components/NavigationBar";
import { AuthProvider } from "./auth/AuthProvider";
import { RequireAdmin, RequireApproved, RequireAuth } from "./auth/guards";
import LoginPage from "./pages/LoginPage";
import PendingPage from "./pages/PendingPage";
import AdminPage from "./pages/AdminPage";
import Dashboard from "./pages/Dashboard";
import Library from "./pages/Library";
import PlaylistDetail from "./pages/PlaylistDetail";
import History from "./pages/History";
import Settings from "./pages/Settings";

/** Navigation shell shared by every approved application route. */
function AppShell() {
  return (
    <DownloadsProvider>
      <div className="flex h-full bg-surface text-on-surface">
        <NavigationDrawer />
        <NavigationRail />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopAppBar />
          <main className="min-h-0 flex-1 overflow-y-auto">
            <Outlet />
          </main>
          <NavigationBar />
        </div>
      </div>
    </DownloadsProvider>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            <Route element={<RequireAuth />}>
              <Route path="/pending" element={<PendingPage />} />

              <Route element={<RequireApproved />}>
                <Route element={<AppShell />}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/library" element={<Library />} />
                  <Route
                    path="/library/playlist/:id"
                    element={<PlaylistDetail />}
                  />
                  <Route path="/history" element={<History />} />
                  <Route path="/settings" element={<Settings />} />

                  <Route element={<RequireAdmin />}>
                    <Route path="/admin" element={<AdminPage />} />
                  </Route>
                </Route>
              </Route>
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  );
}
