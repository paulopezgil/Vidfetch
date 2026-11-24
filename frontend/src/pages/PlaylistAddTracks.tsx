import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { Track } from "../types/v2";
import { formatDuration } from "../lib";
import {
  addUserPlaylistTrack,
  getUserPlaylist,
  listTracks,
  removeUserPlaylistTrack,
} from "../lib/api";
import {
  groupTracksByDay,
  mediaTypeFor,
  trackIcon,
  type MediaType,
} from "../lib/trackDisplay";
import Button from "../components/Button";
import Card from "../components/Card";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import FilterChip from "../components/FilterChip";
import Icon from "../components/Icon";
import IconButton from "../components/IconButton";
import SearchBar from "../components/SearchBar";
import Spinner from "../components/Spinner";
import Thumbnail from "../components/Thumbnail";
import { useToast } from "../components/Toast";
import { useMediaToken } from "../lib/useMediaToken";

type Filter = "all" | "videos" | "audio" | "images";

const PAGE = 20;

const filters: { value: Filter; label: string }[] = [
  { value: "all", label: "Tot" },
  { value: "videos", label: "Vídeos" },
  { value: "audio", label: "Àudio" },
  { value: "images", label: "Imatges" },
];

/**
 * Track picker for one curated playlist.
 *
 * Only membership can change here: every row has a single add/remove action,
 * with no playback, preview, download or delete affordances.
 */
export default function PlaylistAddTracks() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [playlistName, setPlaylistName] = useState("");
  const [membershipError, setMembershipError] = useState<string | null>(null);
  const [membershipLoading, setMembershipLoading] = useState(true);
  /** Tracks the server reports as members. */
  const [members, setMembers] = useState<Set<string>>(new Set());
  /** Adds and removes stored in the offline queue, not yet on the server. */
  const [pendingAdds, setPendingAdds] = useState<Set<string>>(new Set());
  const [pendingRemoves, setPendingRemoves] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<Set<string>>(new Set());

  const [items, setItems] = useState<Track[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [searchInput, setSearchInput] = useState("");
  /** Trimmed query that actually reaches `GET /api/tracks`. */
  const [query, setQuery] = useState("");

  const searchActive = query.length > 0;

  const loadMembership = useCallback(async () => {
    setMembershipLoading(true);
    try {
      const playlist = await getUserPlaylist(id);
      setPlaylistName(playlist.name);
      setMembers(new Set(playlist.items.map((item) => item.id)));
      setMembershipError(null);
    } catch (e) {
      setMembershipError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut carregar la llista de reproducció.",
      );
    } finally {
      setMembershipLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setPlaylistName("");
    setMembers(new Set());
    setPendingAdds(new Set());
    setPendingRemoves(new Set());
    void loadMembership();
  }, [loadMembership]);

  const refreshList = useCallback(async () => {
    setLoading(true);
    try {
      const page = await listTracks({
        limit: PAGE,
        offset,
        q: query || undefined,
      });
      setItems(page.items);
      setTotal(page.total);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’han pogut carregar els tracks.",
      );
    } finally {
      setLoading(false);
    }
  }, [offset, query]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const submitSearch = useCallback((value: string) => {
    const next = value.trim();
    setQuery((current) => (current === next ? current : next));
    setOffset(0);
  }, []);

  function handleSearchChange(value: string) {
    setSearchInput(value);
    // Clearing the field drops the filter immediately, without a submit.
    if (value.trim() === "" && query !== "") {
      setQuery("");
      setOffset(0);
    }
  }

  /** Server membership overlaid with the changes still waiting in the queue. */
  const membership = useMemo(() => {
    const next = new Set(members);
    pendingAdds.forEach((trackId) => next.add(trackId));
    pendingRemoves.forEach((trackId) => next.delete(trackId));
    return next;
  }, [members, pendingAdds, pendingRemoves]);

  const toggleMembership = useCallback(
    async (track: Track) => {
      if (busy.has(track.id)) return;
      const inPlaylist = membership.has(track.id);
      setBusy((prev) => new Set(prev).add(track.id));

      // Optimistic overlay, rolled back only when the server rejects the call.
      // A queued result stays in the overlay so a later membership refresh
      // cannot hide a change that is still waiting to be replayed.
      if (inPlaylist) {
        setPendingAdds((prev) => {
          if (!prev.has(track.id)) return prev;
          const next = new Set(prev);
          next.delete(track.id);
          return next;
        });
        setPendingRemoves((prev) => new Set(prev).add(track.id));
      } else {
        setPendingRemoves((prev) => {
          if (!prev.has(track.id)) return prev;
          const next = new Set(prev);
          next.delete(track.id);
          return next;
        });
        setPendingAdds((prev) => new Set(prev).add(track.id));
      }

      try {
        if (inPlaylist) {
          const result = await removeUserPlaylistTrack(id, track.id);
          if (result.queued) {
            toast(result.message, "info");
          } else {
            setMembers((prev) => {
              const next = new Set(prev);
              next.delete(track.id);
              return next;
            });
            setPendingRemoves((prev) => {
              const next = new Set(prev);
              next.delete(track.id);
              return next;
            });
          }
        } else {
          const result = await addUserPlaylistTrack(id, track.id);
          if (result.queued) {
            toast(result.message, "info");
          } else {
            // The response carries the full ordered membership.
            setMembers(new Set(result.data.items.map((item) => item.id)));
            setPendingAdds((prev) => {
              const next = new Set(prev);
              next.delete(track.id);
              return next;
            });
          }
        }
      } catch (e) {
        if (inPlaylist) {
          setPendingRemoves((prev) => {
            const next = new Set(prev);
            next.delete(track.id);
            return next;
          });
        } else {
          setPendingAdds((prev) => {
            const next = new Set(prev);
            next.delete(track.id);
            return next;
          });
        }
        toast(
          e instanceof Error
            ? e.message
            : inPlaylist
              ? "No s’ha pogut treure el track de la playlist"
              : "No s’ha pogut afegir el track a la playlist",
          "error",
        );
      } finally {
        setBusy((prev) => {
          const next = new Set(prev);
          next.delete(track.id);
          return next;
        });
      }
    },
    [busy, membership, id, toast],
  );

  const visibleTracks = useMemo(() => {
    if (filter === "all") return items;
    const mediaType: MediaType =
      filter === "videos" ? "video" : filter === "audio" ? "audio" : "image";
    return items.filter((item) => mediaTypeFor(item) === mediaType);
  }, [items, filter]);

  const trackDays = useMemo(
    () => groupTracksByDay(visibleTracks),
    [visibleTracks],
  );

  if (membershipLoading) {
    return (
      <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
        <Spinner /> S’està carregant la playlist…
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-4 py-6 sm:px-6 lg:px-8">
      <Link
        to={`/playlists/${id}`}
        className="inline-flex w-fit items-center gap-1.5 rounded-full pr-3 text-label-large text-primary hover:text-primary/80"
      >
        <Icon name="arrow_back" className="text-[20px]" />
        {playlistName || "Playlist"}
      </Link>

      <header className="space-y-1">
        <h1 className="break-words text-headline-small text-on-surface">
          Afegeix tracks
        </h1>
        <p className="text-body-medium text-on-surface-variant">
          {membership.size} {membership.size === 1 ? "track" : "tracks"}
        </p>
      </header>

      {membershipError ? (
        <EmptyState
          icon="playlist_remove"
          title="No s’ha trobat la llista de reproducció"
          description={membershipError}
          action={
            <Button variant="outlined" onClick={() => void loadMembership()}>
              <Icon name="refresh" className="text-[18px]" />
              Torna-ho a provar
            </Button>
          }
        />
      ) : (
        <>
          {error ? <ErrorBanner message={error} onRetry={refreshList} /> : null}

          <SearchBar
            value={searchInput}
            onChange={handleSearchChange}
            onSubmit={() => submitSearch(searchInput)}
            label="Cerca tracks"
            placeholder="Cerca per títol, artista o àlbum"
            loading={loading}
          />

          <div className="flex gap-2 overflow-x-auto pb-1">
            {filters.map((option) => (
              <FilterChip
                key={option.value}
                label={option.label}
                selected={filter === option.value}
                onClick={() => setFilter(option.value)}
              />
            ))}
          </div>

          {loading && items.length === 0 ? (
            <div className="flex items-center justify-center gap-3 py-20 text-body-medium text-on-surface-variant">
              <Spinner /> S’estan carregant els tracks…
            </div>
          ) : (
            <>
              {trackDays.map((day) => (
                <section key={day.key} className="space-y-2">
                  <h2 className="px-1 text-title-medium text-on-surface">
                    {day.label}
                  </h2>
                  <Card
                    variant="outlined"
                    className="divide-y divide-outline-variant overflow-hidden"
                  >
                    {day.items.map((item) => (
                      <PickerRow
                        key={item.id}
                        track={item}
                        inPlaylist={membership.has(item.id)}
                        busy={busy.has(item.id)}
                        onToggle={() => void toggleMembership(item)}
                      />
                    ))}
                  </Card>
                </section>
              ))}

              {!error && visibleTracks.length === 0 ? (
                searchActive ? (
                  <EmptyState
                    icon="search_off"
                    title="Cap resultat per a la cerca"
                    description={`No hi ha cap track que coincideixi amb «${query}». Prova un altre terme o neteja la cerca.`}
                  />
                ) : total === 0 ? (
                  <EmptyState
                    icon="library_music"
                    title="Encara no hi ha tracks a la biblioteca"
                    description="Descarrega vídeos o àudio des de l’Inici i apareixeran aquí per afegir-los a la playlist."
                    action={
                      <Button variant="outlined" onClick={() => navigate("/")}>
                        <Icon name="home" className="text-[18px]" />
                        Ves a l’Inici
                      </Button>
                    }
                  />
                ) : (
                  <EmptyState
                    icon="filter_alt_off"
                    title="Aquí no hi ha res"
                    description="Prova un altre filtre per veure més tracks de la biblioteca."
                  />
                )
              ) : null}

              {total > PAGE ? (
                <div className="flex items-center justify-between text-body-medium text-on-surface-variant">
                  <span>
                    {offset + 1}–{Math.min(offset + PAGE, total)} de {total}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outlined"
                      size="sm"
                      disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - PAGE))}
                    >
                      Anterior
                    </Button>
                    <Button
                      variant="outlined"
                      size="sm"
                      disabled={offset + PAGE >= total}
                      onClick={() => setOffset(offset + PAGE)}
                    >
                      Següent
                    </Button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </>
      )}
    </div>
  );
}

function PickerRow({
  track,
  inPlaylist,
  busy,
  onToggle,
}: {
  track: Track;
  inPlaylist: boolean;
  busy: boolean;
  onToggle: () => void;
}) {
  // A custom cover is already signed; otherwise mint a thumbnail token.
  const { token } = useMediaToken(
    track.cover_url || !track.thumbnail_path ? null : track.asset_id,
  );
  const src = track.cover_url ?? token?.thumbnail_url ?? null;
  const credit = [track.artist, track.album]
    .map((value) => value.trim())
    .filter((value) => value.length > 0)
    .join(" · ");

  return (
    <div className="flex items-center gap-3 p-4">
      <Thumbnail src={src} icon={trackIcon(track)} className="aspect-video w-20" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-title-small text-on-surface">
          {track.title}
        </p>
        <p className="mt-0.5 flex items-center gap-2 truncate text-body-small text-on-surface-variant">
          {track.duration_seconds ? (
            <span className="tabular-nums">
              {formatDuration(track.duration_seconds)}
            </span>
          ) : null}
          {credit ? <span className="truncate">{credit}</span> : null}
        </p>
      </div>
      <IconButton
        variant={inPlaylist ? "filled" : "tonal"}
        label={inPlaylist ? "Treu de la playlist" : "Afegeix a la playlist"}
        ariaPressed={inPlaylist}
        disabled={busy}
        onClick={onToggle}
      >
        {busy ? (
          <Spinner className="text-[20px]" />
        ) : (
          <Icon name={inPlaylist ? "check_circle" : "add"} className="text-[20px]" />
        )}
      </IconButton>
    </div>
  );
}
