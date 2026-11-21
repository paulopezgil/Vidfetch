-- Vidfetch v2 initial schema.
--
-- This migration defines application identity, the global media cache, durable
-- per-user jobs, playlists, and the admin audit trail. RLS is enabled on every
-- application table; the FastAPI backend is the only component that performs
-- normal reads and writes.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------

create table if not exists public.profiles (
    id            uuid primary key references auth.users (id) on delete cascade,
    email         text not null default '',
    is_approved   boolean not null default false,
    app_role      text not null default 'user'
                  check (app_role in ('user', 'admin')),
    approved_at   timestamptz,
    approved_by   uuid references public.profiles (id) on delete set null,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index if not exists profiles_is_approved_idx on public.profiles (is_approved);
create index if not exists profiles_app_role_idx on public.profiles (app_role);
create index if not exists profiles_email_idx on public.profiles (lower(email));

-- ---------------------------------------------------------------------------
-- media_assets: global deduplication registry
-- ---------------------------------------------------------------------------

create table if not exists public.media_assets (
    id                    uuid primary key default gen_random_uuid(),
    canonical_id          text not null,
    extractor_key         text not null default '',
    source_url            text not null default '',
    title                 text not null default '',
    duration_seconds      integer,
    options_hash          text not null,
    options_schema_version integer not null default 1,
    format_selector       text not null default '',
    output_ext            text,
    file_path             text,
    file_size_bytes       bigint,
    file_sha256           text,
    status                text not null default 'processing'
                          check (status in ('processing', 'ready', 'failed')),
    error                 text not null default '',
    attempts              integer not null default 0,
    claimed_at            timestamptz,
    lease_until           timestamptz,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    last_accessed_at      timestamptz not null default now(),
    constraint media_assets_canonical_options_key
        unique (canonical_id, options_hash),
    constraint media_assets_file_path_relative
        check (
            file_path is null
            or (
                file_path <> ''
                and file_path not like '/%'
                and position('..' in file_path) = 0
            )
        )
);

create index if not exists media_assets_status_lease_idx
    on public.media_assets (status, lease_until);
create index if not exists media_assets_last_accessed_idx
    on public.media_assets (last_accessed_at);
create index if not exists media_assets_canonical_idx
    on public.media_assets (canonical_id);

-- ---------------------------------------------------------------------------
-- playlists
-- ---------------------------------------------------------------------------

create table if not exists public.playlists (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references public.profiles (id) on delete cascade,
    canonical_id    text not null,
    source_url      text not null default '',
    title           text not null default '',
    channel         text not null default '',
    thumbnail_path  text,
    item_count      integer not null default 0,
    options_hash    text not null,
    format_selector text not null default '',
    status          text not null default 'pending'
                    check (status in ('pending', 'downloading', 'ready', 'partial', 'failed', 'cancelled')),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint playlists_user_canonical_options_key
        unique (user_id, canonical_id, options_hash),
    constraint playlists_thumbnail_path_relative
        check (thumbnail_path is null or (thumbnail_path <> '' and thumbnail_path not like '/%'))
);

create index if not exists playlists_user_created_idx
    on public.playlists (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- download_jobs: durable per-user queue and history
-- ---------------------------------------------------------------------------

create table if not exists public.download_jobs (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid not null references public.profiles (id) on delete cascade,
    asset_id          uuid references public.media_assets (id) on delete set null,
    playlist_id       uuid references public.playlists (id) on delete set null,
    kind              text not null default 'video'
                      check (kind in ('video', 'playlist', 'playlist_item')),
    source_url        text not null default '',
    title             text not null default '',
    options_hash      text not null default '',
    format_selector   text not null default '',
    idempotency_key   text,
    status            text not null default 'queued'
                      check (status in ('queued', 'resolving', 'downloading', 'processing', 'ready', 'failed', 'cancelled')),
    progress          numeric(5, 2) not null default 0
                      check (progress >= 0 and progress <= 100),
    downloaded_bytes  bigint not null default 0,
    total_bytes       bigint not null default 0,
    speed             numeric not null default 0,
    eta_seconds       integer,
    error             text not null default '',
    attempts          integer not null default 0,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    started_at        timestamptz,
    completed_at      timestamptz
);

create unique index if not exists download_jobs_user_idempotency_key_idx
    on public.download_jobs (user_id, idempotency_key)
    where idempotency_key is not null;
create index if not exists download_jobs_user_created_idx
    on public.download_jobs (user_id, created_at desc);
create index if not exists download_jobs_status_created_idx
    on public.download_jobs (status, created_at);
create index if not exists download_jobs_asset_idx
    on public.download_jobs (asset_id);

-- ---------------------------------------------------------------------------
-- playlist_items
-- ---------------------------------------------------------------------------

create table if not exists public.playlist_items (
    id                uuid primary key default gen_random_uuid(),
    playlist_id       uuid not null references public.playlists (id) on delete cascade,
    position          integer not null,
    canonical_id      text not null default '',
    source_url        text not null default '',
    title             text not null default '',
    duration_seconds  integer,
    asset_id          uuid references public.media_assets (id) on delete set null,
    job_id            uuid references public.download_jobs (id) on delete set null,
    status            text not null default 'pending'
                      check (status in ('pending', 'downloading', 'ready', 'failed', 'cancelled')),
    error             text not null default '',
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint playlist_items_position_key unique (playlist_id, position)
);

create unique index if not exists playlist_items_playlist_canonical_idx
    on public.playlist_items (playlist_id, canonical_id)
    where canonical_id <> '';
create index if not exists playlist_items_playlist_idx
    on public.playlist_items (playlist_id, position);

-- ---------------------------------------------------------------------------
-- admin_audit_log
-- ---------------------------------------------------------------------------

create table if not exists public.admin_audit_log (
    id              uuid primary key default gen_random_uuid(),
    actor_id        uuid references public.profiles (id) on delete set null,
    action          text not null,
    target_user_id  uuid references public.profiles (id) on delete set null,
    metadata        jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);

create index if not exists admin_audit_log_created_idx
    on public.admin_audit_log (created_at desc);

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
    before update on public.profiles
    for each row execute function public.set_updated_at();

drop trigger if exists media_assets_set_updated_at on public.media_assets;
create trigger media_assets_set_updated_at
    before update on public.media_assets
    for each row execute function public.set_updated_at();

drop trigger if exists download_jobs_set_updated_at on public.download_jobs;
create trigger download_jobs_set_updated_at
    before update on public.download_jobs
    for each row execute function public.set_updated_at();

drop trigger if exists playlists_set_updated_at on public.playlists;
create trigger playlists_set_updated_at
    before update on public.playlists
    for each row execute function public.set_updated_at();

drop trigger if exists playlist_items_set_updated_at on public.playlist_items;
create trigger playlist_items_set_updated_at
    before update on public.playlist_items
    for each row execute function public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Supabase Auth -> profiles synchronization
-- ---------------------------------------------------------------------------

create or replace function public.handle_auth_user_change()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    if tg_op = 'INSERT' then
        insert into public.profiles (id, email)
        values (new.id, coalesce(new.email, ''))
        on conflict (id) do update
            set email = excluded.email,
                updated_at = now();
    elsif tg_op = 'UPDATE' then
        update public.profiles
           set email = coalesce(new.email, ''),
               updated_at = now()
         where id = new.id;
    end if;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert or update of email on auth.users
    for each row execute function public.handle_auth_user_change();

-- ---------------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------------

alter table public.profiles enable row level security;
alter table public.media_assets enable row level security;
alter table public.download_jobs enable row level security;
alter table public.playlists enable row level security;
alter table public.playlist_items enable row level security;
alter table public.admin_audit_log enable row level security;

-- Clients may read only their own profile. All writes go through the backend.
revoke all on public.profiles from anon, authenticated;
grant select (id, email, is_approved, app_role, created_at, updated_at)
    on public.profiles to authenticated;
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own
    on public.profiles
    for select
    to authenticated
    using (auth.uid() = id);

-- No direct client access to the cache, jobs, playlists, or audit log.
revoke all on public.media_assets from anon, authenticated;
revoke all on public.download_jobs from anon, authenticated;
revoke all on public.playlists from anon, authenticated;
revoke all on public.playlist_items from anon, authenticated;
revoke all on public.admin_audit_log from anon, authenticated;

comment on table public.profiles is
    'Application identity and approval state, synchronized from auth.users.';
comment on table public.media_assets is
    'Global deduplication cache keyed by (canonical_id, options_hash).';
comment on table public.download_jobs is
    'Durable per-user queue, progress, and download history.';
comment on table public.playlists is
    'Per-user playlist metadata.';
comment on table public.playlist_items is
    'Per-user playlist items, each linked to a shared media asset or job.';
comment on table public.admin_audit_log is
    'Audit trail for approval, revocation, role, and asset actions.';
