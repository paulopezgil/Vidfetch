import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Track, UserPlaylist } from "../types/v2";
import {
  getUserPlaylist,
  listSharedUserPlaylists,
  listUserPlaylists,
} from "../lib/api";
import Button from "../components/Button";
import Card from "../components/Card";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import PlaylistCollage from "../components/PlaylistCollage";
import PlaylistDialog from "../components/PlaylistDialog";
import Spinner from "../components/Spinner";
import { useToast } from "../components/Toast";

const PLAYLIST_LIMIT = 100;
/** Covers shown in one collage tile. */
const COLLAGE_TRACKS = 4;

/**
 * The user's own curated playlists and the ones shared with them.
 *
 * Downloaded YouTube/source playlists are not listed here: their tracks are
 * grouped by artist and playlist title under Artists/Albums and appear in the
 * Songs/Videos library. The `/imported/:id` route stays available for old
 * bookmarks and direct links.
 */
export default function Playlists() {
  const toast = useToast();
  const navigate = useNavigate();
  const [curated, setCurated] = useState<UserPlaylist[]>([]);
  const [shared, setShared] = useState<UserPlaylist[]>([]);
  const [covers, setCovers] = useState<Record<string, Track[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [curatedFailed, setCuratedFailed] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [curatedResult, sharedResult] = await Promise.allSettled([
        listUserPlaylists({ limit: PLAYLIST_LIMIT }),
        listSharedUserPlaylists({ limit: PLAYLIST_LIMIT }),
      ]);
      const failures: string[] = [];

      if (curatedResult.status === "fulfilled") {
        setCurated(
          Array.isArray(curatedResult.value.items)
            ? curatedResult.value.items
            : [],
        );
      } else {
        failures.push(
          curatedResult.reason instanceof Error
            ? curatedResult.reason.message
            : "No s’han pogut carregar les teves llistes.",
        );
      }

      if (sharedResult.status === "fulfilled") {
        setShared(
          Array.isArray(sharedResult.value.items)
            ? sharedResult.value.items
            : [],
        );
      } else {
        failures.push(
          sharedResult.reason instanceof Error
            ? sharedResult.reason.message
            : "No s’han pogut carregar les llistes compartides amb tu.",
        );
      }

      setError(failures[0] ?? null);
      setCuratedFailed(curatedResult.status === "rejected");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Curated and shared playlists only carry a relative cover path, so the
  // collage uses the first few tracks of each playlist. Failures leave the
  // placeholder.
  const collagePlaylists = useMemo(
    () => [...curated, ...shared],
    [curated, shared],
  );
  useEffect(() => {
    if (collagePlaylists.length === 0) {
      setCovers({});
      return;
    }
    let cancelled = false;
    // Playlists without tracks have no collage to build.
    const ids = [
      ...new Set(
        collagePlaylists
          .filter((playlist) => playlist.track_count > 0)
          .map((playlist) => playlist.id),
      ),
    ];
    if (ids.length === 0) {
      setCovers({});
      return;
    }

    void Promise.allSettled(ids.map((playlistId) => getUserPlaylist(playlistId)))
      .then((results) => {
        if (cancelled) return;
        const next: Record<string, Track[]> = {};
        results.forEach((result, index) => {
          if (result.status === "fulfilled") {
            next[ids[index]] = Array.isArray(result.value.items)
              ? result.value.items.slice(0, COLLAGE_TRACKS)
              : [];
          }
        });
        setCovers(next);
      });

    return () => {
      cancelled = true;
    };
  }, [collagePlaylists]);

  const handleCreated = useCallback(
    (playlist: UserPlaylist) => {
      toast(`«${playlist.name}» creada`, "success");
      navigate(`/playlists/${encodeURIComponent(playlist.id)}`);
    },
    [navigate, toast],
  );

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      <section aria-labelledby="curated-heading" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3 px-1">
          <div className="min-w-0">
            <h2
              id="curated-heading"
              className="text-title-medium text-on-surface"
            >
              Les meves llistes
            </h2>
          </div>
          <Button onClick={() => setCreateOpen(true)}>
            <Icon name="add" className="text-[18px]" />
            Crea una llista
          </Button>
        </div>

        {loading && curated.length === 0 ? (
          <SectionLoading label="S’estan carregant les teves llistes…" />
        ) : curated.length > 0 ? (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {curated.map((playlist) => (
              <li key={playlist.id} className="min-w-0">
                <CuratedPlaylistCard
                  playlist={playlist}
                  tracks={covers[playlist.id] ?? []}
                />
              </li>
            ))}
          </ul>
        ) : !loading && !curatedFailed ? (
          <EmptyState
            icon="queue_music"
            title="Encara no hi ha llistes"
            description="Crea una llista per agrupar cançons en l’ordre que vulguis."
          />
        ) : null}
      </section>

      {shared.length > 0 ? (
        <section aria-labelledby="shared-heading" className="space-y-3">
          <div className="flex items-baseline justify-between gap-3 px-1">
            <div className="min-w-0">
              <h2
                id="shared-heading"
                className="text-title-medium text-on-surface"
              >
                Compartides amb mi
              </h2>
            </div>
            <span className="text-label-medium text-on-surface-variant">
              {shared.length}
            </span>
          </div>

          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {shared.map((playlist) => (
              <li key={playlist.id} className="min-w-0">
                <SharedPlaylistCard
                  playlist={playlist}
                  tracks={covers[playlist.id] ?? []}
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <PlaylistDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSaved={handleCreated}
      />
    </div>
  );
}

function SectionLoading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-1 py-6 text-body-medium text-on-surface-variant">
      <Spinner /> {label}
    </div>
  );
}

function CuratedPlaylistCard({
  playlist,
  tracks,
}: {
  playlist: UserPlaylist;
  tracks: Track[];
}) {
  const count = playlist.track_count;

  return (
    <Card
      variant="elevated"
      className="group h-full overflow-hidden rounded-lg transition-shadow duration-200 hover:shadow-elevation-2 focus-within:shadow-elevation-2"
    >
      <Link
        to={`/playlists/${encodeURIComponent(playlist.id)}`}
        className="flex h-full flex-col rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
      >
        <div className="p-2 pb-0">
          <PlaylistCollage
            tracks={tracks}
            className="aspect-square w-full"
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5 p-3">
          <p className="truncate text-title-small text-on-surface">
            {playlist.name}
          </p>
          {playlist.description ? (
            <p className="truncate text-body-small text-on-surface-variant">
              {playlist.description}
            </p>
          ) : null}
          <p className="mt-auto flex items-center gap-1 pt-1 text-label-medium text-on-surface-variant">
            <Icon name="music_note" className="text-[16px]" />
            {count} {count === 1 ? "cançó" : "cançons"}
          </p>
        </div>
      </Link>
    </Card>
  );
}

function SharedPlaylistCard({
  playlist,
  tracks,
}: {
  playlist: UserPlaylist;
  tracks: Track[];
}) {
  const count = playlist.track_count;
  const owner = playlist.owner_email || "un altre usuari";

  return (
    <Card
      variant="elevated"
      className="group h-full overflow-hidden rounded-lg transition-shadow duration-200 hover:shadow-elevation-2 focus-within:shadow-elevation-2"
    >
      <Link
        to={`/playlists/${encodeURIComponent(playlist.id)}`}
        className="flex h-full flex-col rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
      >
        <div className="p-2 pb-0">
          <PlaylistCollage
            tracks={tracks}
            className="aspect-square w-full"
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5 p-3">
          <p className="truncate text-title-small text-on-surface">
            {playlist.name}
          </p>
          <p className="flex min-w-0 items-center gap-1 text-body-small text-on-surface-variant">
            <Icon name="share" className="shrink-0 text-[14px]" />
            <span className="truncate">Compartida per {owner}</span>
          </p>
          <p className="mt-auto flex items-center gap-1 pt-1 text-label-medium text-on-surface-variant">
            <Icon name="music_note" className="text-[16px]" />
            {count} {count === 1 ? "cançó" : "cançons"}
          </p>
        </div>
      </Link>
    </Card>
  );
}
