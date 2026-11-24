-- User-curated playlists over per-user tracks.
--
-- These are deliberately separate from "public".playlists, which represents
-- a downloaded source playlist (for example a YouTube playlist). A curated
-- playlist contains the user's own track rows in an explicit order, so it is
-- unaffected by source playlist refreshes and never crosses user boundaries.

create table if not exists "public".user_playlists (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references "public".profiles (id) on delete cascade,
    name        text not null,
    description text not null default '',
    cover_path  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    deleted_at  timestamptz,
    constraint user_playlists_name_length
        check (length(btrim(name)) between 1 and 200),
    constraint user_playlists_cover_path_relative
        check (cover_path is null or (cover_path <> '' and cover_path not like '/%'))
);

create index if not exists user_playlists_user_updated_idx
    on "public".user_playlists (user_id, updated_at desc)
    where deleted_at is null;

create table if not exists "public".user_playlist_tracks (
    playlist_id   uuid not null references "public".user_playlists (id) on delete cascade,
    user_track_id uuid not null references "public".user_tracks (id) on delete cascade,
    position      integer not null check (position >= 0),
    added_at      timestamptz not null default now(),
    primary key (playlist_id, user_track_id),
    -- Deferred so a reorder can reassign positions inside one transaction.
    constraint user_playlist_tracks_position_key
        unique (playlist_id, position) deferrable initially deferred
);

create index if not exists user_playlist_tracks_track_idx
    on "public".user_playlist_tracks (user_track_id);

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

drop trigger if exists user_playlists_set_updated_at on "public".user_playlists;
create trigger user_playlists_set_updated_at
    before update on "public".user_playlists
    for each row execute function "public".set_updated_at();

-- ---------------------------------------------------------------------------
-- Security posture
-- ---------------------------------------------------------------------------

alter table "public".user_playlists enable row level security;
alter table "public".user_playlist_tracks enable row level security;

-- No direct client access: every read and write goes through the backend.
revoke all on "public".user_playlists from anon, authenticated;
revoke all on "public".user_playlist_tracks from anon, authenticated;

comment on table "public".user_playlists is
    'Per-user curated playlists, separate from downloaded source playlists.';
comment on table "public".user_playlist_tracks is
    'Ordered membership of per-user tracks inside a curated playlist.';

grant all on "public".user_playlists to service_role;
grant all on "public".user_playlist_tracks to service_role;
