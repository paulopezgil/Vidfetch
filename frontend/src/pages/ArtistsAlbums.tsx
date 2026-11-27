import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import GroupEditDialog, {
  type GroupEditKind,
} from "../components/GroupEditDialog";
import Icon from "../components/Icon";
import IconButton from "../components/IconButton";
import Menu from "../components/Menu";
import NowPlayingIndicator from "../components/NowPlayingIndicator";
import OfflineButton from "../components/OfflineButton";
import SegmentedButton from "../components/SegmentedButton";
import Spinner from "../components/Spinner";
import Thumbnail from "../components/Thumbnail";
import TrackEditDialog from "../components/TrackEditDialog";
import { useToast } from "../components/Toast";
import { usePlayer } from "../player/PlayerProvider";
import { useMediaToken } from "../lib/useMediaToken";
import { mediaTypeFor } from "../lib/trackDisplay";
import { useImageCache } from "../offline/images";

type GroupTab = "artists" | "albums";

interface Group {
  name: string;
  tracks: Track[];
}

const TRACK_LIMIT = 200;

const tabOptions = [
  { value: "artists", label: "Artistes", icon: "person" },
  { value: "albums", label: "Àlbums", icon: "album" },
];

const UNKNOWN_ARTIST = "Artista desconegut";
const UNKNOWN_ALBUM = "Àlbum desconegut";

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
export default function ArtistsAlbums({
  initialTab = "artists",
  embedded = false,
}: {
  /** Section requested by the route, also used to resync on navigation. */
  initialTab?: GroupTab;
  /** Renders inside the Biblioteca hub, which owns the section switch. */
  embedded?: boolean;
}) {
  const [tracks, setTracks] = useState<Track[]>([]);
  const [tab, setTab] = useState<GroupTab>(initialTab);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Track | null>(null);
  const [editingGroup, setEditingGroup] = useState<{
    kind: GroupEditKind;
    name: string;
    tracks: Track[];
  } | null>(null);
  const toast = useToast();
  const [searchParams] = useSearchParams();
  const query = (searchParams.get("q") ?? "").trim();
  const normalizedQuery = query.toLocaleLowerCase("ca");

  // The hub owns the shared search; group only the tracks that match it.
  const filteredTracks = useMemo(() => {
    if (!normalizedQuery) return tracks;
    return tracks.filter((track) =>
      [track.title, track.artist, track.album].some((value) =>
        (value ?? "").toLocaleLowerCase("ca").includes(normalizedQuery),
      ),
    );
  }, [normalizedQuery, tracks]);

  const refresh = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) setLoading(true);
    try {
      const page = await listTracks({ limit: TRACK_LIMIT });
      setTracks(page.items);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No s’han pogut carregar les cançons.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The hub switch navigates between `/library/albums` and
  // `/library/artists`; follow the new route and close any drill-down.
  useEffect(() => {
    setTab(initialTab);
    setSelected(null);
  }, [initialTab]);

  // A new query starts from the overview instead of a stale drill-down.
  useEffect(() => {
    setSelected(null);
  }, [normalizedQuery]);

  const artists = useMemo(
    () => groupTracks(filteredTracks, (track) => track.artist, UNKNOWN_ARTIST),
    [filteredTracks],
  );
  const albums = useMemo(
    () => groupTracks(filteredTracks, (track) => track.album, UNKNOWN_ALBUM),
    [filteredTracks],
  );

  const groups = tab === "artists" ? artists : albums;
  const selectedGroup = selected
    ? groups.find((group) => group.name === selected) ?? null
    : null;

  const changeTab = useCallback((value: string) => {
    setTab(value === "albums" ? "albums" : "artists");
    setSelected(null);
  }, []);

  const handleSaved = useCallback(
    (updated: Track) => {
      // Replacing the track in place regroups the artist/album buckets, and
      // the selected drill-down reflects the new metadata immediately.
      setTracks((prev) =>
        prev.map((track) => (track.id === updated.id ? updated : track)),
      );
      toast("Cançó actualitzada", "success");
    },
    [toast],
  );

  const handleGroupApplied = useCallback(
    (failed: number) => {
      // Refetch so the regroup reflects every saved row, not just optimistic
      // copies; a partial failure still refreshes what did save. The refresh
      // is silent so the dialog never unmounts mid-retry.
      void refresh({ silent: true });
      if (failed === 0) toast("Canvis aplicats", "success");
    },
    [refresh, toast],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
        <Spinner /> S’està carregant la música…
      </div>
    );
  }

  const containerClass = embedded
    ? "w-full space-y-6"
    : "mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 lg:px-8";

  return (
    <div className={containerClass}>
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}

      {!error && tracks.length === 0 ? (
        <EmptyState
          icon="library_music"
          title="Encara no hi ha artistes ni àlbums"
          description="Les cançons descarregades apareixeran aquí, agrupades per artista i àlbum."
        />
      ) : null}

      {!error && tracks.length > 0 && filteredTracks.length === 0 ? (
        <EmptyState
          icon="search_off"
          title="Cap resultat per a la cerca"
          description={`No hi ha cap cançó que coincideixi amb «${query}». Prova un altre terme o neteja la cerca.`}
        />
      ) : null}

      {tracks.length > 0 && filteredTracks.length > 0 ? (
        <>
          {!embedded ? (
            <div className="px-1">
              <SegmentedButton
                options={tabOptions}
                value={tab}
                onChange={changeTab}
                label="Agrupa la música per"
              />
            </div>
          ) : null}

          {selectedGroup ? (
            <section
              aria-labelledby="group-heading"
              className="space-y-3"
            >
              <div className="flex items-center gap-2">
                <IconButton
                  label={
                    tab === "artists"
                      ? "Torna als artistes"
                      : "Torna als àlbums"
                  }
                  onClick={() => setSelected(null)}
                >
                  <Icon name="arrow_back" className="text-[20px]" />
                </IconButton>
                <div className="min-w-0 flex-1">
                  <h2
                    id="group-heading"
                    className="truncate text-title-large text-on-surface"
                  >
                    {selectedGroup.name}
                  </h2>
                  <p className="text-body-small text-on-surface-variant">
                    {selectedGroup.tracks.length}{" "}
                    {selectedGroup.tracks.length === 1 ? "cançó" : "cançons"}
                  </p>
                </div>
                <Menu
                  label="Més accions"
                  actions={[
                    {
                      id: "edit-group",
                      label:
                        tab === "albums" ? "Edita l’àlbum" : "Edita el grup",
                      icon: "edit",
                      onSelect: () =>
                        setEditingGroup({
                          kind: tab === "albums" ? "album" : "artist",
                          // The fallback bucket has no real name to prefill.
                          name:
                            selectedGroup.name === UNKNOWN_ARTIST ||
                            selectedGroup.name === UNKNOWN_ALBUM
                              ? ""
                              : selectedGroup.name,
                          tracks: selectedGroup.tracks,
                        }),
                    },
                  ]}
                />
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
                    onEdit={() => setEditing(track)}
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
                  {tab === "artists" ? "Artistes" : "Àlbums"}
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

      <TrackEditDialog
        open={editing !== null}
        track={editing}
        onClose={() => setEditing(null)}
        onSaved={handleSaved}
      />

      <GroupEditDialog
        open={editingGroup !== null}
        kind={editingGroup?.kind ?? "artist"}
        name={editingGroup?.name ?? ""}
        tracks={editingGroup?.tracks ?? []}
        onClose={() => setEditingGroup(null)}
        onApplied={handleGroupApplied}
      />
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
        <GroupArtwork group={group} variant={variant} />
        <span className="min-w-0 self-stretch">
          <span className="block truncate text-title-small text-on-surface">
            {group.name}
          </span>
          <span className="mt-0.5 block text-label-medium text-on-surface-variant">
            {count} {count === 1 ? "cançó" : "cançons"}
          </span>
        </span>
      </button>
    </Card>
  );
}

/**
 * Group artwork from the first track: a square album cover, or a vinyl-style
 * record for artists. Neither reads as a user profile avatar, and the fallback
 * icons are music glyphs (`album` / `graphic_eq`) rather than `person`.
 */
function GroupArtwork({
  group,
  variant,
}: {
  group: Group;
  variant: GroupTab;
}) {
  const first = group.tracks[0] ?? null;
  const { token } = useMediaToken(
    first && !first.cover_url && !first.thumbnail_url && first.thumbnail_path
      ? first.asset_id
      : null,
  );
  const artwork =
    first?.cover_url ?? first?.thumbnail_url ?? token?.thumbnail_url ?? null;

  if (variant === "albums") {
    return <AlbumArtwork src={artwork} />;
  }

  return <VinylArtwork src={artwork} />;
}

/** Rounded-square cover art, with an album glyph when nothing is available. */
function AlbumArtwork({ src }: { src: string | null }) {
  const [failed, setFailed] = useState(false);
  useImageCache(src);

  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className="block aspect-square w-full rounded-md object-cover"
      />
    );
  }

  return (
    <span className="flex aspect-square w-full items-center justify-center rounded-md bg-surface-container-high text-on-surface-variant">
      <Icon name="album" className="text-[40px]" />
    </span>
  );
}

/** Circular record with groove ring and center spindle. */
function VinylArtwork({ src }: { src: string | null }) {
  const [failed, setFailed] = useState(false);
  useImageCache(src);

  return (
    <span
      aria-hidden="true"
      className="relative block aspect-square w-full"
    >
      {src && !failed ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
          className="block h-full w-full rounded-full object-cover"
        />
      ) : (
        <span className="flex h-full w-full items-center justify-center rounded-full bg-surface-container-high text-on-surface-variant">
          <Icon name="graphic_eq" className="text-[40px]" />
        </span>
      )}
      {/* Vinyl grooves plus a center label and spindle hole. */}
      <span className="pointer-events-none absolute inset-[8%] rounded-full border border-on-surface/10" />
      <span className="pointer-events-none absolute left-1/2 top-1/2 h-[26%] w-[26%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-container/95 ring-1 ring-outline-variant" />
      <span className="pointer-events-none absolute left-1/2 top-1/2 h-[7%] w-[7%] -translate-x-1/2 -translate-y-1/2 rounded-full bg-on-primary-container/60" />
    </span>
  );
}

function TrackRow({
  track,
  queue,
  onEdit,
}: {
  track: Track;
  queue: Track[];
  onEdit: () => void;
}) {
  const { current, isPlaying, playTrack, togglePlay } = usePlayer();
  const toast = useToast();
  // Only ask for a token when the track has neither signed artwork URL nor a
  // thumbnail path; the API now sends `thumbnail_url` for ready tracks.
  const { token } = useMediaToken(
    !track.cover_url && !track.thumbnail_url && track.thumbnail_path
      ? track.asset_id
      : null,
  );
  const [downloading, setDownloading] = useState(false);
  const artwork =
    track.cover_url ?? track.thumbnail_url ?? token?.thumbnail_url ?? null;
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
      className={`flex flex-wrap items-center gap-3 p-3 ${
        active ? "bg-surface-container" : ""
      }`}
    >
      <Thumbnail
        src={artwork}
        icon="music_note"
        className="h-11 w-11 rounded-md"
      />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <p className="truncate text-body-large text-on-surface">
            {track.title}
          </p>
          {active ? <NowPlayingIndicator /> : null}
        </div>
        <p className="mt-0.5 truncate text-body-small text-on-surface-variant">
          {credit || "Artista desconegut"}
          {duration ? ` · ${duration}` : ""}
        </p>
      </div>
      <div className="flex w-full min-w-0 items-center justify-between gap-1.5 sm:w-auto sm:justify-end">
        <div className="flex min-w-0 items-center gap-1.5">
          <IconButton
            variant={playing ? "filled" : "tonal"}
            label={playing ? "Pausa" : "Reprodueix"}
            onClick={() => (active ? togglePlay() : playTrack(track, queue))}
          >
            <Icon
              name={playing ? "pause" : "play_arrow"}
              className="text-[20px]"
            />
          </IconButton>
          {!isImage ? (
            <OfflineButton
              assetId={track.asset_id}
              title={track.title}
              kind={mediaType === "audio" ? "audio" : "video"}
            />
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Menu
            label="Més accions"
            actions={[
              ...(!isImage
                ? [
                    {
                      id: "download",
                      label: "Descarrega el fitxer",
                      icon: "download",
                      onSelect: () => void handleDownload(),
                    },
                  ]
                : []),
              {
                id: "edit",
                label: "Edita els detalls",
                icon: "edit",
                onSelect: onEdit,
              },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
