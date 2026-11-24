import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { PlaylistV2 } from "../types/v2";
import { listPlaylists } from "../lib/api";
import Card from "../components/Card";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import Spinner from "../components/Spinner";
import Thumbnail from "../components/Thumbnail";
import Icon from "../components/Icon";

const PLAYLIST_LIMIT = 100;

/** Grid of the playlists imported by the signed-in account. */
export default function Playlists() {
  const [playlists, setPlaylists] = useState<PlaylistV2[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const page = await listPlaylists({ limit: PLAYLIST_LIMIT });
      setPlaylists(page.items);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not load playlists.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
        <Spinner /> Loading playlists…
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      {!error && playlists.length === 0 ? (
        <EmptyState
          icon="queue_music"
          title="No playlists yet"
          description="Playlists you import from Home will appear here."
        />
      ) : null}

      {playlists.length > 0 ? (
        <section aria-labelledby="playlists-heading" className="space-y-3">
          <div className="flex items-baseline justify-between gap-3 px-1">
            <h2
              id="playlists-heading"
              className="text-title-medium text-on-surface"
            >
              Playlists
            </h2>
            <span className="text-label-medium text-on-surface-variant">
              {playlists.length}
            </span>
          </div>

          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {playlists.map((playlist) => (
              <li key={playlist.id} className="min-w-0">
                <PlaylistCard playlist={playlist} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function PlaylistCard({ playlist }: { playlist: PlaylistV2 }) {
  const count = playlist.item_count;
  const subtitle = `${count} ${count === 1 ? "video" : "videos"}`;

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
