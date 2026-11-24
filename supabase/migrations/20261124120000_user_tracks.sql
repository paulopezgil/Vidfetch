-- Per-user track metadata on top of the global media cache.
--
-- A user_tracks row is the user's own library entry for a shared media asset.
-- It holds user-editable metadata (title, artist, album, cover) while the
-- audio/video file remains a single row in media_assets, shared by every user.
--
-- The table is populated from ready download jobs (backfill plus trigger) and
-- is the basis for the Tracks, Artists, and Albums views. Rows are never
-- deleted when the shared asset is evicted; deleted_at is reserved for the
-- offline-sync tombstone used by clients.

create table if not exists "public".user_tracks (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references "public".profiles (id) on delete cascade,
    asset_id        uuid not null references "public".media_assets (id) on delete cascade,
    custom_title    text not null default '',
    custom_artist   text not null default '',
    custom_album    text not null default '',
    cover_path      text,
    downloaded_at   timestamptz not null default now(),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    deleted_at      timestamptz,
    constraint user_tracks_user_asset_key unique (user_id, asset_id),
    constraint user_tracks_cover_path_relative
        check (cover_path is null or (cover_path <> '' and cover_path not like '/%'))
);

create index if not exists user_tracks_user_downloaded_idx
    on "public".user_tracks (user_id, downloaded_at desc);

create index if not exists user_tracks_user_artist_idx
    on "public".user_tracks (user_id, lower(custom_artist))
    where deleted_at is null;

create index if not exists user_tracks_user_album_idx
    on "public".user_tracks (user_id, lower(custom_album))
    where deleted_at is null;

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

drop trigger if exists user_tracks_set_updated_at on "public".user_tracks;
create trigger user_tracks_set_updated_at
    before update on "public".user_tracks
    for each row execute function "public".set_updated_at();

-- ---------------------------------------------------------------------------
-- Keep the track registry in step with successful downloads
-- ---------------------------------------------------------------------------

create or replace function "public".sync_user_track_from_job()
returns trigger
language plpgsql
security definer
set search_path = "public", pg_temp
as $$
begin
    if new.status = 'ready' and new.asset_id is not null then
        insert into "public".user_tracks (user_id, asset_id, downloaded_at)
        values (new.user_id, new.asset_id, coalesce(new.completed_at, now()))
        on conflict (user_id, asset_id) do nothing;
    end if;
    return new;
end;
$$;

drop trigger if exists download_jobs_sync_user_track on "public".download_jobs;
create trigger download_jobs_sync_user_track
    after insert or update of status, asset_id on "public".download_jobs
    for each row execute function "public".sync_user_track_from_job();

-- Backfill from downloads that became ready before this table existed.
insert into "public".user_tracks (user_id, asset_id, downloaded_at, created_at, updated_at)
select j.user_id,
       j.asset_id,
       coalesce(j.completed_at, j.created_at),
       j.created_at,
       j.created_at
  from "public".download_jobs j
  join "public".media_assets a on a.id = j.asset_id
 where j.status = 'ready'
   and j.asset_id is not null
   and a.status = 'ready'
on conflict (user_id, asset_id) do nothing;

-- ---------------------------------------------------------------------------
-- Security posture
-- ---------------------------------------------------------------------------

alter table "public".user_tracks enable row level security;

-- No direct client access: every read and write goes through the backend.
revoke all on "public".user_tracks from anon, authenticated;

comment on table "public".user_tracks is
    'Per-user metadata and library link for a shared media asset.';

-- The trusted server-side role bypasses RLS and owns all operations.
grant all on "public".user_tracks to service_role;
