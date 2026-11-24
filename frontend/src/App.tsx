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
import Tracks from "./pages/Tracks";
import Playlists from "./pages/Playlists";
import PlaylistDetail from "./pages/PlaylistDetail";
import UserPlaylistDetail from "./pages/UserPlaylistDetail";
import ArtistsAlbums from "./pages/ArtistsAlbums";

/** Navigation shell shared by every approved application route. */
function AppShell() {
  return (
    <DownloadsProvider>
      <PlayerProvider>
        <div className="flex h-full bg-surface text-on-surface">
          <NavigationDrawer />
          <NavigationRail />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopAppBar />
            <main className="min-h-0 flex-1 overflow-y-auto">
              <Outlet />
            </main>
            <PlayerBar />
            <NavigationBar />
          </div>
        </div>
      </PlayerProvider>
    </DownloadsProvider>
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
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            <Route element={<RequireAuth />}>
              <Route path="/pending" element={<PendingPage />} />

              <Route element={<RequireApproved />}>
                <Route element={<AppShell />}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/tracks" element={<Tracks />} />
                  <Route path="/playlists" element={<Playlists />} />
                  <Route
                    path="/playlists/:id"
                    element={<UserPlaylistDetail />}
                  />
                  <Route path="/imported/:id" element={<PlaylistDetail />} />
                  <Route path="/artists" element={<ArtistsAlbums />} />
                  <Route
                    path="/library"
                    element={<Navigate to="/tracks" replace />}
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
        </BrowserRouter>
      </AuthProvider>
    </ToastProvider>
  );
}
