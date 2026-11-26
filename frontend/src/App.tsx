import { lazy, Suspense } from "react";
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useParams,
} from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { DownloadsProvider } from "./downloads/DownloadsProvider";
import { PlayerProvider } from "./player/PlayerProvider";
import PlayerBar from "./components/PlayerBar";
import VideoSurface from "./components/VideoSurface";
import Spinner from "./components/Spinner";
import TopAppBar from "./components/TopAppBar";
import OfflineBanner from "./components/OfflineBanner";
import NavigationDrawer from "./components/NavigationDrawer";
import NavigationRail from "./components/NavigationRail";
import NavigationBar from "./components/NavigationBar";
import { AuthProvider } from "./auth/AuthProvider";
import { RequireAdmin, RequireApproved, RequireAuth } from "./auth/guards";
import AutoOfflineTransfer from "./offline/AutoOfflineTransfer";

// Route-level code splitting: the shell and player stay in the initial bundle,
// every page (and the dialogs it owns) loads on first navigation.
const LoginPage = lazy(() => import("./pages/LoginPage"));
const PendingPage = lazy(() => import("./pages/PendingPage"));
const AdminPage = lazy(() => import("./pages/AdminPage"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Library = lazy(() => import("./pages/Library"));
const Playlists = lazy(() => import("./pages/Playlists"));
const PlaylistDetail = lazy(() => import("./pages/PlaylistDetail"));
const UserPlaylistDetail = lazy(() => import("./pages/UserPlaylistDetail"));
const PlaylistAddTracks = lazy(() => import("./pages/PlaylistAddTracks"));
const ArtistsAlbums = lazy(() => import("./pages/ArtistsAlbums"));
const InstallGuide = lazy(() => import("./pages/InstallGuide"));
const Settings = lazy(() => import("./pages/Settings"));

/** Shared loading state for every lazily loaded route. */
function RouteFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-[50vh] items-center justify-center gap-3 px-4 text-body-medium text-on-surface-variant"
    >
      <Spinner />
      <span>S’està carregant…</span>
    </div>
  );
}

/** Navigation shell shared by every approved application route. */
function AppShell() {
  return (
    <>
      <a
        href="#main-content"
        className="fixed left-4 top-3 z-[60] -translate-y-24 rounded-full bg-primary px-4 py-2 text-label-large text-on-primary shadow-elevation-2 transition-transform focus:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-on-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
      >
        Salta al contingut
      </a>
      <DownloadsProvider>
        <PlayerProvider>
          <AutoOfflineTransfer />
          <div className="flex h-full bg-surface text-on-surface">
            <NavigationDrawer />
            <NavigationRail />
            <div className="flex min-w-0 flex-1 flex-col">
              <TopAppBar />
              <OfflineBanner />
              <main
                id="main-content"
                tabIndex={-1}
                className="min-h-0 flex-1 overflow-y-auto focus:outline-none"
              >
                <Suspense fallback={<RouteFallback />}>
                  <Outlet />
                </Suspense>
              </main>
              <PlayerBar />
              <VideoSurface />
              <NavigationBar />
            </div>
          </div>
        </PlayerProvider>
      </DownloadsProvider>
    </>
  );
}

/** Preserve old library playlist links after the navigation restructure. */
function LegacyPlaylistRedirect() {
  const { id = "" } = useParams();
  return <Navigate to={`/imported/${encodeURIComponent(id)}`} replace />;
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrowserRouter>
          {/* Boundary for the pre-shell pages; the shell has its own nested
              Suspense so navigation never unmounts the player or top bar. */}
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />

              <Route element={<RequireAuth />}>
                <Route path="/pending" element={<PendingPage />} />

                <Route element={<RequireApproved />}>
                  <Route element={<AppShell />}>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/songs" element={<Library kind="audio" />} />
                    <Route path="/videos" element={<Library kind="video" />} />
                    <Route
                      path="/tracks"
                      element={<Navigate to="/songs" replace />}
                    />
                    <Route path="/playlists" element={<Playlists />} />
                    <Route
                      path="/playlists/:id/add"
                      element={<PlaylistAddTracks />}
                    />
                    <Route
                      path="/playlists/:id"
                      element={<UserPlaylistDetail />}
                    />
                    <Route path="/imported/:id" element={<PlaylistDetail />} />
                    <Route path="/artists" element={<ArtistsAlbums />} />
                    <Route path="/install" element={<InstallGuide />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route
                      path="/library"
                      element={<Navigate to="/songs" replace />}
                    />
                    <Route
                      path="/library/playlist/:id"
                      element={<LegacyPlaylistRedirect />}
                    />

                    <Route element={<RequireAdmin />}>
                      <Route path="/admin" element={<AdminPage />} />
                    </Route>
                  </Route>
                </Route>
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  );
}
