import { useEffect, useState } from "react";
import type { Track } from "../types/v2";
import { getMediaToken } from "../lib/api";
import Icon from "./Icon";

interface PlaylistCollageProps {
  /** Tracks in playlist order; the first four supply the collage images. */
  tracks: Track[];
  className?: string;
}

/** Maximum number of covers combined into one collage. */
const MAX_TILES = 4;

/**
 * Cover collage for a curated playlist.
 *
 * Tracks expose a signed `cover_url` only when the user uploaded custom art,
 * so missing covers fall back to the short-lived thumbnail token of the track
 * asset. Up to four images are arranged in a grid; with no artwork the
 * component renders the Material music placeholder instead.
 */
export default function PlaylistCollage({
  tracks,
  className = "",
}: PlaylistCollageProps) {
  const [sources, setSources] = useState<string[]>([]);
  const picked = tracks.slice(0, MAX_TILES);
  // Refetch only when the selected tracks (or their covers) change.
  const signature = picked
    .map(
      (track) =>
        `${track.id}:${track.cover_url ?? ""}:${track.thumbnail_url ?? ""}`,
    )
    .join("|");

  useEffect(() => {
    let cancelled = false;
    if (picked.length === 0) {
      setSources([]);
      return;
    }

    void Promise.all(
      picked.map(async (track) => {
        if (track.cover_url) return track.cover_url;
        if (track.thumbnail_url) return track.thumbnail_url;
        if (!track.asset_id || !track.thumbnail_path) return null;
        try {
          const token = await getMediaToken(track.asset_id);
          return token.thumbnail_url;
        } catch {
          return null;
        }
      }),
    ).then((urls) => {
      if (cancelled) return;
      const available = urls.filter((url): url is string => Boolean(url));
      setSources(available);
    });

    return () => {
      cancelled = true;
    };
    // `signature` captures every input the request depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const columns = sources.length > 1 ? "grid-cols-2" : "grid-cols-1";

  return (
    <div
      aria-hidden="true"
      className={`grid overflow-hidden rounded-lg bg-surface-container-high ${columns} ${className}`}
    >
      {sources.length > 0 ? (
        sources.map((src, index) => (
          <CollageTile key={`${index}-${src}`} src={src} />
        ))
      ) : (
        <div className="flex h-full w-full items-center justify-center text-on-surface-variant">
          <Icon name="queue_music" className="text-[32px]" />
        </div>
      )}
    </div>
  );
}

/** One collage cell; a broken image leaves a neutral surface tile. */
function CollageTile({ src }: { src: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return <span className="block min-h-0 bg-surface-container-high" />;
  }

  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="block h-full min-h-0 w-full object-cover"
    />
  );
}
