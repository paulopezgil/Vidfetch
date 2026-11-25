import { useCallback, useEffect, useMemo, useState } from "react";
import type { Track } from "../types/v2";
import { formatDuration } from "../lib";
import {
  getMediaToken,
  listTracks,
  triggerDownload,
  withDownloadFlag,
} from "../lib/api";
import Card from "../components/Card";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import IconButton from "../components/IconButton";
import OfflineButton from "../components/OfflineButton";
import SegmentedButton from "../components/SegmentedButton";
import Spinner from "../components/Spinner";
import Thumbnail from "../components/Thumbnail";
import { useToast } from "../components/Toast";
import { usePlayer } from "../player/PlayerProvider";
import { useMediaToken } from "../lib/useMediaToken";
import { mediaTypeFor } from "../lib/trackDisplay";

type GroupTab = "artists" | "albums";

interface Group {
  name: string;
  tracks: Track[];
}

const TRACK_LIMIT = 200;

const tabOptions = [
  { value: "artists", label: "Artists", icon: "person" },
  { value: "albums", label: "Albums", icon: "album" },
];

/**
 * Group tracks by a trimmed metadata field, folding blank values into the
 * supplied fallback and keeping the fallback bucket last.
 */
function groupTracks(
  tracks: Track[],
  pick: (track: Track) => string,
  fallback: string,
): Group[] {
  const buckets = new Map<string, Track[]>();
  for (const track of tracks) {
    const name = pick(track).trim() || fallback;
    const bucket = buckets.get(name);
    if (bucket) bucket.push(track);
    else buckets.set(name, [track]);
  }

  return [...buckets.entries()]
    .map(([name, groupItems]) => ({ name, tracks: groupItems }))
    .sort((a, b) => {
      if (a.name === fallback) return 1;
      if (b.name === fallback) return -1;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });
}

/** Artists and albums derived from the caller's tracks, with drill-down. */
export default function ArtistsAlbums() {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [tab, setTab] = useState<GroupTab>("artists");
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const page = await listTracks({ limit: TRACK_LIMIT });
      setTracks(page.items);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load your tracks.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const artists = useMemo(
    () => groupTracks(tracks, (track) => track.artist, "Unknown artist"),
    [tracks],
  );
  const albums = useMemo(
    () => groupTracks(tracks, (track) => track.album, "Unknown album"),
    [tracks],
  );

  const groups = tab === "artists" ? artists : albums;
  const selectedGroup = selected
    ? groups.find((group) => group.name === selected) ?? null
    : null;

  const changeTab = useCallback((value: string) => {
    setTab(value === "albums" ? "albums" : "artists");
    setSelected(null);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
        <Spinner /> Loading your music…
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      {!error && tracks.length === 0 ? (
        <EmptyState
          icon="person"
          title="No artists or albums yet"
          description="Downloaded tracks will appear here, grouped by their artist and album."
        />
      ) : null}

      {tracks.length > 0 ? (
        <>
          <div className="px-1">
            <SegmentedButton
              options={tabOptions}
              value={tab}
              onChange={changeTab}
              label="Group your music by"
            />
          </div>

          {selectedGroup ? (
            <section
              aria-labelledby="group-heading"
              className="space-y-3"
            >
              <div className="flex items-center gap-2">
                <IconButton
                  label={`Back to ${tab === "artists" ? "artists" : "albums"}`}
                  onClick={() => setSelected(null)}
                >
                  <Icon name="arrow_back" className="text-[20px]" />
                </IconButton>
                <div className="min-w-0">
                  <h2
                    id="group-heading"
                    className="truncate text-title-large text-on-surface"
                  >
                    {selectedGroup.name}
                  </h2>
                  <p className="text-body-small text-on-surface-variant">
                    {selectedGroup.tracks.length}{" "}
                    {selectedGroup.tracks.length === 1 ? "track" : "tracks"}
                  </p>
                </div>
              </div>

              <Card
                variant="outlined"
                className="divide-y divide-outline-variant overflow-hidden"
              >
                {selectedGroup.tracks.map((track) => (
                  <TrackRow
                    key={track.id}
                    track={track}
                    queue={selectedGroup.tracks}
                  />
                ))}
              </Card>
            </section>
          ) : (
            <section aria-labelledby="group-grid-heading" className="space-y-3">
              <div className="flex items-baseline justify-between gap-3 px-1">
                <h2
                  id="group-grid-heading"
                  className="text-title-medium text-on-surface"
                >
                  {tab === "artists" ? "Artists" : "Albums"}
                </h2>
                <span className="text-label-medium text-on-surface-variant">
                  {groups.length}
                </span>
              </div>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {groups.map((group) => (
                  <li key={group.name} className="min-w-0">
                    <GroupCard
                      group={group}
                      variant={tab}
                      onSelect={() => setSelected(group.name)}
                    />
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}

function GroupCard({
  group,
  variant,
  onSelect,
}: {
  group: Group;
  variant: GroupTab;
  onSelect: () => void;
}) {
  const count = group.tracks.length;
  const initial = Array.from(group.name)[0]?.toUpperCase() ?? "?";

  return (
    <Card
      variant="elevated"
      className="h-full overflow-hidden rounded-lg transition-shadow duration-200 hover:shadow-elevation-2 focus-within:shadow-elevation-2"
    >
      <button
        type="button"
        onClick={onSelect}
        className="flex h-full w-full flex-col items-center gap-3 p-3 text-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
      >
        {variant === "artists" ? (
          <span
            aria-hidden="true"
            className="flex h-20 w-20 items-center justify-center rounded-full bg-primary-container text-headline-medium text-on-primary-container"
          >
            {initial}
          </span>
        ) : (
          <Thumbnail
            src={null}
            icon="album"
            className="aspect-square w-full rounded-md"
          />
        )}
        <span className="min-w-0">
          <span className="block truncate text-title-small text-on-surface">
            {group.name}
          </span>
          <span className="mt-0.5 block text-label-medium text-on-surface-variant">
            {count} {count === 1 ? "track" : "tracks"}
          </span>
        </span>
      </button>
    </Card>
  );
}

function TrackRow({ track, queue }: { track: Track; queue: Track[] }) {
  const { current, isPlaying, playTrack, togglePlay } = usePlayer();
  const toast = useToast();
  // Only ask for a token when there is no cover and the asset has a thumbnail.
  const { token } = useMediaToken(
    !track.cover_url && track.thumbnail_path ? track.asset_id : null,
  );
  const [downloading, setDownloading] = useState(false);
  const artwork = track.cover_url ?? token?.thumbnail_url ?? null;
  const active = current?.id === track.id;
  const playing = active && isPlaying;
  const mediaType = mediaTypeFor(track);
  const isImage = mediaType === "image";
  const credit = [track.artist, track.album]
    .map((value) => value.trim())
    .filter((value) => value.length > 0)
    .join(" · ");
  const duration = formatDuration(track.duration_seconds);

  async function handleDownload() {
    if (downloading || !track.asset_id) return;
    setDownloading(true);
    try {
      const fresh = await getMediaToken(track.asset_id);
      if (!fresh?.url) {
        toast("No s’ha pogut preparar el fitxer per descarregar.", "error");
        return;
      }
      triggerDownload(withDownloadFlag(fresh.url));
    } catch (e) {
      toast(
        e instanceof Error
          ? e.message
          : "No s’ha pogut preparar el fitxer per descarregar.",
        "error",
      );
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div
      className={`flex items-center gap-3 p-3 ${
        active ? "bg-surface-container" : ""
      }`}
    >
      <Thumbnail
        src={artwork}
        icon="music_note"
        className="h-11 w-11 rounded-md"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-body-large text-on-surface">
          {track.title}
        </p>
        <p className="mt-0.5 truncate text-body-small text-on-surface-variant">
          {credit || "Unknown artist"}
          {duration ? ` · ${duration}` : ""}
        </p>
      </div>
      {!isImage ? (
        <>
          <OfflineButton
            assetId={track.asset_id}
            title={track.title}
            kind={mediaType === "audio" ? "audio" : "video"}
          />
          <IconButton
            variant="tonal"
            label="Descarrega el fitxer"
            onClick={() => void handleDownload()}
            disabled={downloading}
          >
            {downloading ? (
              <Spinner className="text-[20px]" />
            ) : (
              <Icon name="download" className="text-[20px]" />
            )}
          </IconButton>
        </>
      ) : null}
      <IconButton
        variant={playing ? "filled" : "tonal"}
        label={playing ? "Pause" : "Play"}
        onClick={() => (active ? togglePlay() : playTrack(track, queue))}
      >
        <Icon
          name={playing ? "pause" : "play_arrow"}
          className="text-[20px]"
        />
      </IconButton>
    </div>
  );
}
