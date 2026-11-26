-- Track metadata defaults and curated-playlist sharing.
--
-- ``download_jobs.artist`` / ``download_jobs.album`` let the worker record the
-- source channel and the source playlist name. The user-track trigger copies
-- those defaults when a ready job first creates a track, while leaving any
-- metadata the user has already edited untouched.
--
-- ``playlist_items.channel`` caches the per-item channel so a retry can restore
-- the same artist metadata without re-extracting the video.
--
-- ``user_playlist_shares`` makes a curated playlist readable by another
-- approved account. It never transfers ownership and never exposes the
-- owner's user_tracks mutations to the shared viewer.

alter table "public".download_jobs
    add column if not exists artist text not null default '';
alter table "public".download_jobs
    add column if not exists album text not null default '';

alter table "public".playlist_items
    add column if not exists channel text not null default '';

create table if not exists "public".user_playlist_shares (
    playlist_id uuid not null
        references "public".user_playlists (id) on delete cascade,
    user_id     uuid not null
        references "public".profiles (id) on delete cascade,
    created_at  timestamptz not null default now(),
    primary key (playlist_id, user_id)
);

create index if not exists user_playlist_shares_user_idx
    on "public".user_playlist_shares (user_id, created_at desc);

-- The trigger now seeds artist/album from the job. On conflict it only fills
-- blank values, so a track the user renamed is never overwritten by a later
-- download of the same shared asset.
create or replace function "public".sync_user_track_from_job()
returns trigger
language plpgsql
as $$
begin
    if new.status = 'ready' and new.asset_id is not null then
        insert into "public".user_tracks (
            user_id,
            asset_id,
            downloaded_at,
            custom_artist,
            custom_album
        )
        values (
            new.user_id,
            new.asset_id,
            coalesce(new.completed_at, now()),
            coalesce(new.artist, ''),
            coalesce(new.album, '')
        )
        on conflict (user_id, asset_id) do update set
            custom_artist = case
                when "public".user_tracks.custom_artist = ''
                    then excluded.custom_artist
                else "public".user_tracks.custom_artist
            end,
            custom_album = case
                when "public".user_tracks.custom_album = ''
                    then excluded.custom_album
                else "public".user_tracks.custom_album
            end;
    end if;
    return new;
end;
$$;
