import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { PlaylistV2, Track, UserPlaylist } from "../types/v2";
import {
  getUserPlaylist,
  listPlaylists,
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
import Thumbnail from "../components/Thumbnail";
import { useToast } from "../components/Toast";

const PLAYLIST_LIMIT = 100;
/** Covers shown in one collage tile. */
const COLLAGE_TRACKS = 4;

/**
 * Curated playlists first (the user's own ordered selections), then the
 * playlists imported from source sites under a separate heading.
 */
export default function Playlists() {
  const toast = useToast();
  const navigate = useNavigate();
  const [curated, setCurated] = useState<UserPlaylist[]>([]);
  const [imported, setImported] = useState<PlaylistV2[]>([]);
  const [covers, setCovers] = useState<Record<string, Track[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [failed, setFailed] = useState({ curated: false, imported: false });
  const [createOpen, setCreateOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [curatedResult, importedResult] = await Promise.allSettled([
        listUserPlaylists({ limit: PLAYLIST_LIMIT }),
        listPlaylists({ limit: PLAYLIST_LIMIT }),
      ]);
      const failures: string[] = [];

      if (curatedResult.status === "fulfilled") {
        setCurated(curatedResult.value.items);
      } else {
        failures.push(
          curatedResult.reason instanceof Error
            ? curatedResult.reason.message
            : "Could not load your playlists.",
        );
      }

      if (importedResult.status === "fulfilled") {
        setImported(importedResult.value.items);
      } else {
        failures.push(
          importedResult.reason instanceof Error
            ? importedResult.reason.message
            : "Could not load imported playlists.",
        );
      }

      setError(failures[0] ?? null);
      setFailed({
        curated: curatedResult.status === "rejected",
        imported: importedResult.status === "rejected",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Curated playlists only carry a relative cover path, so the collage uses
  // the first few tracks of each playlist. Failures leave the placeholder.
  useEffect(() => {
    if (curated.length === 0) {
      setCovers({});
      return;
    }
    let cancelled = false;
    // Playlists without tracks have no collage to build.
    const ids = curated
      .filter((playlist) => playlist.track_count > 0)
      .map((playlist) => playlist.id);
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
            next[ids[index]] = result.value.items.slice(0, COLLAGE_TRACKS);
          }
        });
        setCovers(next);
      });

    return () => {
      cancelled = true;
    };
  }, [curated]);

  const handleCreated = useCallback(
    (playlist: UserPlaylist) => {
      toast(`«${playlist.name}» creada`, "success");
      navigate(`/playlists/${encodeURIComponent(playlist.id)}`);
    },
    [navigate, toast],
  );

  // An import that failed entirely produced nothing usable, so it must not be
  // shown as a successful playlist. Partially successful imports stay visible.
  const visibleImported = imported.filter(
    (playlist) => playlist.status !== "failed",
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
              Your playlists
            </h2>
            <p className="text-body-small text-on-surface-variant">
              Your own ordered selections of tracks.
            </p>
          </div>
          <Button onClick={() => setCreateOpen(true)}>
            <Icon name="add" className="text-[18px]" />
            Create playlist
          </Button>
        </div>

        {loading && curated.length === 0 ? (
          <SectionLoading label="Loading your playlists…" />
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
        ) : !loading && !failed.curated ? (
          <EmptyState
            icon="queue_music"
            title="No playlists yet"
            description="Create a playlist to group tracks in whatever order you like."
          />
        ) : null}
      </section>

      <section aria-labelledby="imported-heading" className="space-y-3">
        <div className="flex items-baseline justify-between gap-3 px-1">
          <div className="min-w-0">
            <h2
              id="imported-heading"
              className="text-title-medium text-on-surface"
            >
              Imported
            </h2>
            <p className="text-body-small text-on-surface-variant">
              Playlists downloaded from a source site.
            </p>
          </div>
          <span className="text-label-medium text-on-surface-variant">
            {visibleImported.length}
          </span>
        </div>

        {loading && visibleImported.length === 0 ? (
          <SectionLoading label="Loading imported playlists…" />
        ) : visibleImported.length > 0 ? (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {visibleImported.map((playlist) => (
              <li key={playlist.id} className="min-w-0">
                <ImportedPlaylistCard playlist={playlist} />
              </li>
            ))}
          </ul>
        ) : !loading && !failed.imported ? (
          <EmptyState
            icon="playlist_play"
            title="No imported playlists"
            description="Playlists you import from Home will appear here."
          />
        ) : null}
      </section>

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
            {count} {count === 1 ? "track" : "tracks"}
          </p>
        </div>
      </Link>
    </Card>
  );
}

function ImportedPlaylistCard({ playlist }: { playlist: PlaylistV2 }) {
  const count = playlist.item_count;
  const subtitle = `${count} ${count === 1 ? "video" : "videos"}`;

  return (
    <Card
      variant="elevated"
      className="group h-full overflow-hidden rounded-lg transition-shadow duration-200 hover:shadow-elevation-2 focus-within:shadow-elevation-2"
    >
      <Link
        to={`/imported/${encodeURIComponent(playlist.id)}`}
        className="flex h-full flex-col rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
      >
        <div className="p-2 pb-0">
          <Thumbnail
            src={playlist.thumbnail_url ?? null}
            icon="queue_music"
            className="aspect-video w-full rounded-md"
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5 p-3">
          <p className="truncate text-title-small text-on-surface">
            {playlist.title || "Playlist"}
          </p>
          {playlist.channel ? (
            <p className="truncate text-body-small text-on-surface-variant">
              {playlist.channel}
            </p>
          ) : null}
          <p className="mt-auto flex items-center gap-1 pt-1 text-label-medium text-on-surface-variant">
            <Icon name="playlist_play" className="text-[16px]" />
            {subtitle}
          </p>
        </div>
      </Link>
    </Card>
  );
}
