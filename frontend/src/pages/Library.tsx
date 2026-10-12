import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { LibraryFile, LibraryResponse, Playlist } from "../types";
import { formatBytes, formatDate } from "../lib";
import { deleteFile, deletePlaylist, fileUrl, listLibrary } from "../api";
import Thumbnail from "../components/Thumbnail";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import IconButton from "../components/IconButton";
import Icon from "../components/Icon";
import Card from "../components/Card";
import FilterChip from "../components/FilterChip";
import Spinner from "../components/Spinner";
import ConfirmDialog from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";

type Tab = "all" | "files" | "playlists" | "video" | "audio";

const tabs: { value: Tab; label: string }[] = [
  { value: "all", label: "Tot" },
  { value: "files", label: "Fitxers" },
  { value: "playlists", label: "Llistes" },
  { value: "video", label: "Vídeo" },
  { value: "audio", label: "Àudio" },
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
      setError(e instanceof Error ? e.message : "No s’ha pogut carregar la biblioteca.");
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
        toast("Fitxer eliminat", "success");
      } else {
        await deletePlaylist(pendingDelete.id);
        toast("Llista de reproducció eliminada", "success");
      }
      setPendingDelete(null);
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "No s’ha pogut eliminar", "error");
    }
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
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      {loading ? (
        <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
          <Spinner /> S’està carregant la biblioteca…
        </div>
      ) : (
        <>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {tabs.map((t) => (
              <FilterChip
                key={t.value}
                label={t.label}
                selected={tab === t.value}
                onClick={() => setTab(t.value)}
              />
            ))}
          </div>

          {showPlaylists && visiblePlaylists.length > 0 ? (
            <section className="space-y-2">
              {tab === "all" ? (
                <h2 className="px-1 text-title-medium text-on-surface">
                  Llistes de reproducció
                </h2>
              ) : null}
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {visiblePlaylists.map((p) => (
                  <PlaylistRow
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
              </Card>
            </section>
          ) : null}

          {showFiles && visibleFiles.length > 0 ? (
            <section className="space-y-2">
              {tab === "all" ? (
                <h2 className="px-1 text-title-medium text-on-surface">
                  Fitxers
                </h2>
              ) : null}
              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
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
              </Card>
            </section>
          ) : null}

          {!error &&
          visibleFiles.length === 0 &&
          visiblePlaylists.length === 0 ? (
            <EmptyState
              icon="folder_open"
              title={tab === "all" ? "La biblioteca és buida" : "Aquí no hi ha res"}
              description={
                tab === "all"
                  ? "Els vídeos i les llistes de reproducció que descarreguis apareixeran aquí."
                  : "Prova un altre filtre o descarrega contingut nou des de l’Inici."
              }
            />
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Voleu eliminar ${
          pendingDelete?.kind === "file"
            ? "el fitxer"
            : "la llista de reproducció"
        }?`}
        message={
          <>
            S’eliminarà{" "}
            <span className="font-medium text-on-surface">
              {pendingDelete?.label}
            </span>{" "}
            del disc. Així i tot, es conserva el registre a l’historial de
            descàrregues.
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
  const icon = file.media_type === "audio" ? "music_note" : "movie";
  return (
    <div className="flex flex-wrap items-center gap-3 p-4">
      <Thumbnail
        src={file.thumbnail_url}
        icon={icon}
        className="aspect-video w-20"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-title-small text-on-surface">
          {file.title}
        </p>
        <p className="mt-0.5 text-body-small text-on-surface-variant">
          {formatBytes(file.size)} · {file.ext.toUpperCase()} ·{" "}
          {formatDate(new Date(file.mtime * 1000).toISOString())}
        </p>
      </div>
      <div className="flex w-full items-center gap-1.5 sm:w-auto">
        <IconButton
          href={fileUrl(file.filename)}
          variant="tonal"
          label="Descarrega el fitxer"
        >
          <Icon name="download" className="text-[20px]" />
        </IconButton>
        <IconButton
          variant="danger"
          label="Elimina el fitxer"
          onClick={onDelete}
        >
          <Icon name="delete" className="text-[20px]" />
        </IconButton>
      </div>
    </div>
  );
}

function PlaylistRow({
  playlist,
  onDelete,
}: {
  playlist: Playlist;
  onDelete: () => void;
}) {
  const hasZip = Boolean(playlist.zip_path);
  return (
    <div className="flex flex-wrap items-center gap-3 p-4 sm:gap-4">
      <Thumbnail
        src={playlist.thumbnail_url}
        icon="playlist_play"
        className="aspect-video w-24"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-title-small text-on-surface">
          {playlist.title}
        </p>
        <p className="mt-0.5 text-body-small text-on-surface-variant">
          {playlist.item_count} vídeos
          {playlist.total_size ? ` · ${formatBytes(playlist.total_size)}` : ""}
        </p>
      </div>
      <div className="flex w-full items-center gap-1.5 sm:w-auto">
        <Link
          to={`/library/playlist/${playlist.playlist_id}`}
          className="inline-flex h-9 items-center gap-1.5 rounded-full bg-secondary-container px-4 text-label-large text-on-secondary-container transition-colors hover:bg-secondary-container/90"
        >
          <Icon name="folder_open" className="text-[18px]" /> Mostra
        </Link>
        {hasZip ? (
          <a
            href={fileUrl(playlist.zip_path)}
            className="inline-flex h-9 items-center gap-1.5 rounded-full border border-outline px-4 text-label-large text-primary transition-colors hover:bg-primary/8"
          >
            <Icon name="folder_zip" className="text-[18px]" /> ZIP
          </a>
        ) : null}
        <IconButton
          variant="danger"
          label="Elimina la llista de reproducció"
          onClick={onDelete}
        >
          <Icon name="delete" className="text-[20px]" />
        </IconButton>
      </div>
    </div>
  );
}
