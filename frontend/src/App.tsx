import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import TopAppBar from "./components/TopAppBar";
import NavigationDrawer from "./components/NavigationDrawer";
import NavigationRail from "./components/NavigationRail";
import NavigationBar from "./components/NavigationBar";
import Dashboard from "./pages/Dashboard";
import Library from "./pages/Library";
import PlaylistDetail from "./pages/PlaylistDetail";
import History from "./pages/History";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <div className="flex h-full bg-surface text-on-surface">
          <NavigationDrawer />
          <NavigationRail />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopAppBar />
            <main className="min-h-0 flex-1 overflow-y-auto">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/library" element={<Library />} />
                <Route
                  path="/library/playlist/:id"
                  element={<PlaylistDetail />}
                />
                <Route path="/history" element={<History />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </main>
            <NavigationBar />
          </div>
        </div>
      </BrowserRouter>
    </ToastProvider>
  );
}
