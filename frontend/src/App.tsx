import { BrowserRouter, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import { ToastProvider } from "./components/Toast";
import Dashboard from "./pages/Dashboard";
import Library from "./pages/Library";
import PlaylistDetail from "./pages/PlaylistDetail";
import History from "./pages/History";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <div className="flex h-full">
          <Sidebar />
          <main className="min-w-0 flex-1 overflow-y-auto">
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
        </div>
      </BrowserRouter>
    </ToastProvider>
  );
}
