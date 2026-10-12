import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Download,
  FolderOpen,
  ListVideo,
  Music,
  Trash2,
  Film,
} from "lucide-react";
import type { LibraryFile, LibraryResponse, Playlist } from "../types";
import { formatBytes, formatDate } from "../lib";
import { deleteFile, deletePlaylist, fileUrl, listLibrary } from "../api";
import Thumbnail from "../components/Thumbnail";
import EmptyState from "../components/EmptyState";
import Spinner from "../components/Spinner";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

type Tab = "all" | "files" | "playlists" | "video" | "audio";

const tabs: { value: Tab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "files", label: "Files" },
  { value: "playlists", label: "Playlists" },
  { value: "video", label: "Video" },
  { value: "audio", label: "Audio" },
];

export default function Library() {
  const toast = useToast();
  const [data, setData] = useState<LibraryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [pendingDelete, setPendingDelete] = useState<{
    kind: "file" | "playlist";
    id: string;
    label: string;
  } | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await listLibrary());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load library.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function confirmDelete() {
    if (!pendingDelete) return;
    try {
      if (pendingDelete.kind === "file") {
        await deleteFile(pendingDelete.id);
        toast("File deleted", "success");
      } else {
        await deletePlaylist(pendingDelete.id);
        toast("Playlist deleted", "success");
      }
      setPendingDelete(null);
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Delete failed", "error");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-fg-secondary">
        <Spinner className="mr-2" /> Loading library…
      </div>
    );
  }

  const files = data?.files ?? [];
  const playlists = data?.playlists ?? [];

  const visibleFiles = files.filter((f) => {
    if (tab === "video") return f.media_type === "video";
    if (tab === "audio") return f.media_type === "audio";
    return tab === "all" || tab === "files";
  });
  const visiblePlaylists = playlists.filter(
    () => tab === "all" || tab === "playlists",
  );

  const showFiles = tab !== "playlists";
  const showPlaylists = tab !== "files" && tab !== "video" && tab !== "audio";

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 sm:px-6">
      <header>
        <h1 className="text-xl font-semibold text-fg">Library</h1>
        <p className="mt-1 text-sm text-fg-secondary">
          Browse your downloaded files and playlists.
        </p>
      </header>

      {error ? (
        <div className="rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        {tabs.map((t) => (
          <button
            key={t.value}
            onClick={() => setTab(t.value)}
            className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/70 ${
              tab === t.value
                ? "bg-brand/15 text-brand-hover"
                : "text-fg-secondary hover:bg-surface-2 hover:text-fg"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {showPlaylists && visiblePlaylists.length > 0 ? (
        <section className="space-y-3">
          {tab === "all" ? (
            <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-secondary">
              Playlists
            </h2>
          ) : null}
          {visiblePlaylists.map((p) => (
            <PlaylistCard
              key={p.playlist_id}
              playlist={p}
              onDelete={() =>
                setPendingDelete({
                  kind: "playlist",
                  id: p.playlist_id,
                  label: p.title,
                })
              }
            />
          ))}
        </section>
      ) : null}

      {showFiles ? (
        <section className="space-y-3">
          {tab === "all" && visibleFiles.length > 0 ? (
            <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-secondary">
              Files
            </h2>
          ) : null}
          {visibleFiles.length > 0 ? (
            <div className="card divide-y divide-line/60">
              {visibleFiles.map((f) => (
                <FileRow
                  key={f.filename}
                  file={f}
                  onDelete={() =>
                    setPendingDelete({
                      kind: "file",
                      id: f.filename,
                      label: f.title,
                    })
                  }
                />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {visibleFiles.length === 0 &&
      visiblePlaylists.length === 0 ? (
        <EmptyState
          icon={<FolderOpen className="h-6 w-6" />}
          title="Your library is empty"
          description="Downloaded videos and playlists will appear here."
        />
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete ${pendingDelete?.kind === "file" ? "file" : "playlist"}?`}
        message={
          <>
            This will remove{" "}
            <span className="font-medium text-fg">{pendingDelete?.label}</span>{" "}
            from disk. Download history is kept.
          </>
        }
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

function FileRow({
  file,
  onDelete,
}: {
  file: LibraryFile;
  onDelete: () => void;
}) {
  const Icon = file.media_type === "audio" ? Music : Film;
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <Thumbnail
        src={file.thumbnail_url}
        className="aspect-video w-20 rounded-md"
        icon={<Icon className="h-4 w-4" />}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg">{file.title}</p>
        <p className="mt-0.5 text-xs text-fg-muted">
          {formatBytes(file.size)} · {file.ext.toUpperCase()} ·{" "}
          {formatDate(new Date(file.mtime * 1000).toISOString())}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <a
          href={fileUrl(file.filename)}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-fg-secondary transition-colors hover:bg-surface-2 hover:text-fg"
          title="Download"
          aria-label="Download file"
        >
          <Download className="h-4 w-4" />
        </a>
        <button
          onClick={onDelete}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-fg-secondary transition-colors hover:bg-danger/15 hover:text-danger"
          title="Delete"
          aria-label="Delete file"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function PlaylistCard({
  playlist,
  onDelete,
}: {
  playlist: Playlist;
  onDelete: () => void;
}) {
  const hasZip = Boolean(playlist.zip_path);
  return (
    <div className="card flex items-center gap-4 p-4">
      <Thumbnail
        src={playlist.thumbnail_url}
        className="aspect-video w-24 rounded-md"
        icon={<ListVideo className="h-5 w-5" />}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-fg">{playlist.title}</p>
        <p className="mt-0.5 text-xs text-fg-muted">
          {playlist.item_count} videos
          {playlist.total_size ? ` · ${formatBytes(playlist.total_size)}` : ""}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Link
          to={`/library/playlist/${playlist.playlist_id}`}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-3 text-[13px] font-medium text-fg transition-colors hover:bg-line/60"
        >
          <ListVideo className="h-4 w-4" /> View
        </Link>
        {hasZip ? (
          <a
            href={fileUrl(playlist.zip_path)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-surface-2 px-3 text-[13px] font-medium text-fg transition-colors hover:bg-line/60"
          >
            <Download className="h-4 w-4" /> ZIP
          </a>
        ) : null}
        <button
          onClick={onDelete}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-fg-secondary transition-colors hover:bg-danger/15 hover:text-danger"
          title="Delete playlist"
          aria-label="Delete playlist"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
