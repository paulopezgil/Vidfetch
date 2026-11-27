-- Backfill legacy ready playlist items into per-item jobs and user tracks.
--
-- Playlists downloaded before the per-item pipeline existed have ready
-- ``playlist_items`` with an ``asset_id`` but no linked ``download_jobs`` row.
-- ``user_tracks`` is created from ready jobs, so those successful songs never
-- reached the Songs/Videos tabs.
--
-- This migration creates one terminal ``playlist_item`` job per ready item that
-- is not linked yet, then stores the job id back on the item. The existing
-- ``download_jobs_sync_user_track`` trigger seeds ``user_tracks`` with the
-- item's channel and the playlist title. The migration is idempotent: only
-- items with ``job_id is null`` are touched.

with inserted as (
    insert into "public".download_jobs (
        user_id,
        asset_id,
        playlist_id,
        kind,
        source_url,
        title,
        options_hash,
        format_selector,
        status,
        progress,
        error,
        artist,
        album,
        started_at,
        completed_at,
        item_index,
        item_count
    )
    select
        p.user_id,
        pi.asset_id,
        pi.playlist_id,
        'playlist_item',
        pi.source_url,
        pi.title,
        p.options_hash,
        p.format_selector,
        'ready',
        100,
        '',
        coalesce(nullif(pi.channel, ''), nullif(p.channel, ''), ''),
        p.title,
        coalesce(pi.created_at, now()),
        coalesce(pi.updated_at, now()),
        pi.position,
        (
            select count(*)
            from "public".playlist_items counted
            where counted.playlist_id = pi.playlist_id
        )
    from "public".playlist_items pi
    join "public".playlists p on p.id = pi.playlist_id
    where pi.status = 'ready'
      and pi.asset_id is not null
      and pi.job_id is null
    returning id, playlist_id, item_index
)
update "public".playlist_items pi
set job_id = inserted.id,
    updated_at = now()
from inserted
where pi.playlist_id = inserted.playlist_id
  and pi.position = inserted.item_index;
