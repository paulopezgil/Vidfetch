-- RLS coverage for the v2 application tables that must have no direct client
-- access: media_assets, download_jobs, playlists, playlist_items, and
-- admin_audit_log.
--
-- Run with:
--   supabase start
--   supabase test db
--
-- The Supabase CLI enables pgTAP before running this file. Everything is
-- rolled back, including the fixture rows.

begin;

select plan(42);

-- ---------------------------------------------------------------------------
-- Fixtures (as the postgres role)
-- ---------------------------------------------------------------------------

insert into auth.users (
    instance_id,
    id,
    aud,
    role,
    email,
    email_confirmed_at,
    created_at,
    updated_at,
    raw_app_meta_data,
    raw_user_meta_data
)
values (
    '00000000-0000-0000-0000-000000000000',
    '11111111-1111-1111-1111-111111111111',
    'authenticated',
    'authenticated',
    'alice@example.com',
    now(),
    now(),
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{}'::jsonb
);

insert into public.media_assets (id, canonical_id, options_hash, status)
values (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'youtube:test-video',
    'options-hash',
    'ready'
);

insert into public.playlists (id, user_id, canonical_id, options_hash)
values (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    '11111111-1111-1111-1111-111111111111',
    'youtube:test-playlist',
    'options-hash'
);

insert into public.download_jobs (id, user_id, asset_id, playlist_id, source_url)
values (
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    '11111111-1111-1111-1111-111111111111',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'https://example.com/watch?v=test'
);

insert into public.playlist_items (id, playlist_id, position, asset_id, job_id)
values (
    'dddddddd-dddd-dddd-dddd-dddddddddddd',
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    0,
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'cccccccc-cccc-cccc-cccc-cccccccccccc'
);

insert into public.admin_audit_log (id, actor_id, action, target_user_id)
values (
    'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee',
    '11111111-1111-1111-1111-111111111111',
    'test.action',
    null
);

-- ---------------------------------------------------------------------------
-- Schema posture
-- ---------------------------------------------------------------------------

select is(
    (
        select count(*)::int
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relname in (
               'media_assets',
               'download_jobs',
               'playlists',
               'playlist_items',
               'admin_audit_log'
           )
           and c.relrowsecurity
    ),
    5,
    'RLS is enabled on every application table'
);

select is(
    (
        select count(*)::int
          from pg_policies
         where schemaname = 'public'
           and tablename in (
               'media_assets',
               'download_jobs',
               'playlists',
               'playlist_items',
               'admin_audit_log'
           )
    ),
    0,
    'application tables expose no direct client policies'
);

-- ---------------------------------------------------------------------------
-- Authenticated client: every operation is denied
-- ---------------------------------------------------------------------------

set local role authenticated;
set local request.jwt.claims =
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}';

-- media_assets
select throws_ok(
    $sql$select * from public.media_assets$sql$,
    '42501', null,
    'authenticated cannot select media_assets'
);
select throws_ok(
    $sql$insert into public.media_assets (canonical_id, options_hash)
         values ('youtube:direct', 'direct-hash')$sql$,
    '42501', null,
    'authenticated cannot insert media_assets'
);
select throws_ok(
    $sql$update public.media_assets
             set title = 'changed'
           where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'$sql$,
    '42501', null,
    'authenticated cannot update media_assets'
);
select throws_ok(
    $sql$delete from public.media_assets
           where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'$sql$,
    '42501', null,
    'authenticated cannot delete media_assets'
);

-- download_jobs
select throws_ok(
    $sql$select * from public.download_jobs$sql$,
    '42501', null,
    'authenticated cannot select download_jobs'
);
select throws_ok(
    $sql$insert into public.download_jobs (user_id, source_url)
         values ('11111111-1111-1111-1111-111111111111',
                 'https://example.com/watch?v=direct')$sql$,
    '42501', null,
    'authenticated cannot insert download_jobs'
);
select throws_ok(
    $sql$update public.download_jobs
             set status = 'ready'
           where id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'$sql$,
    '42501', null,
    'authenticated cannot update download_jobs'
);
select throws_ok(
    $sql$delete from public.download_jobs
           where id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'$sql$,
    '42501', null,
    'authenticated cannot delete download_jobs'
);

-- playlists
select throws_ok(
    $sql$select * from public.playlists$sql$,
    '42501', null,
    'authenticated cannot select playlists'
);
select throws_ok(
    $sql$insert into public.playlists (user_id, canonical_id, options_hash)
         values ('11111111-1111-1111-1111-111111111111',
                 'youtube:direct-playlist', 'direct-hash')$sql$,
    '42501', null,
    'authenticated cannot insert playlists'
);
select throws_ok(
    $sql$update public.playlists
             set title = 'changed'
           where id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'$sql$,
    '42501', null,
    'authenticated cannot update playlists'
);
select throws_ok(
    $sql$delete from public.playlists
           where id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'$sql$,
    '42501', null,
    'authenticated cannot delete playlists'
);

-- playlist_items
select throws_ok(
    $sql$select * from public.playlist_items$sql$,
    '42501', null,
    'authenticated cannot select playlist_items'
);
select throws_ok(
    $sql$insert into public.playlist_items (playlist_id, position)
         values ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 99)$sql$,
    '42501', null,
    'authenticated cannot insert playlist_items'
);
select throws_ok(
    $sql$update public.playlist_items
             set status = 'ready'
           where id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'$sql$,
    '42501', null,
    'authenticated cannot update playlist_items'
);
select throws_ok(
    $sql$delete from public.playlist_items
           where id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'$sql$,
    '42501', null,
    'authenticated cannot delete playlist_items'
);

-- admin_audit_log
select throws_ok(
    $sql$select * from public.admin_audit_log$sql$,
    '42501', null,
    'authenticated cannot select admin_audit_log'
);
select throws_ok(
    $sql$insert into public.admin_audit_log (action)
         values ('direct.write')$sql$,
    '42501', null,
    'authenticated cannot insert admin_audit_log'
);
select throws_ok(
    $sql$update public.admin_audit_log
             set action = 'changed'
           where id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'$sql$,
    '42501', null,
    'authenticated cannot update admin_audit_log'
);
select throws_ok(
    $sql$delete from public.admin_audit_log
           where id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'$sql$,
    '42501', null,
    'authenticated cannot delete admin_audit_log'
);

-- ---------------------------------------------------------------------------
-- Anonymous client: every operation is denied
-- ---------------------------------------------------------------------------

reset role;
set local role anon;
set local request.jwt.claims = '{"role":"anon"}';

-- media_assets
select throws_ok(
    $sql$select * from public.media_assets$sql$,
    '42501', null,
    'anonymous cannot select media_assets'
);
select throws_ok(
    $sql$insert into public.media_assets (canonical_id, options_hash)
         values ('youtube:anon', 'anon-hash')$sql$,
    '42501', null,
    'anonymous cannot insert media_assets'
);
select throws_ok(
    $sql$update public.media_assets
             set title = 'changed'
           where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'$sql$,
    '42501', null,
    'anonymous cannot update media_assets'
);
select throws_ok(
    $sql$delete from public.media_assets
           where id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'$sql$,
    '42501', null,
    'anonymous cannot delete media_assets'
);

-- download_jobs
select throws_ok(
    $sql$select * from public.download_jobs$sql$,
    '42501', null,
    'anonymous cannot select download_jobs'
);
select throws_ok(
    $sql$insert into public.download_jobs (user_id, source_url)
         values ('11111111-1111-1111-1111-111111111111',
                 'https://example.com/watch?v=anon')$sql$,
    '42501', null,
    'anonymous cannot insert download_jobs'
);
select throws_ok(
    $sql$update public.download_jobs
             set status = 'ready'
           where id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'$sql$,
    '42501', null,
    'anonymous cannot update download_jobs'
);
select throws_ok(
    $sql$delete from public.download_jobs
           where id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'$sql$,
    '42501', null,
    'anonymous cannot delete download_jobs'
);

-- playlists
select throws_ok(
    $sql$select * from public.playlists$sql$,
    '42501', null,
    'anonymous cannot select playlists'
);
select throws_ok(
    $sql$insert into public.playlists (user_id, canonical_id, options_hash)
         values ('11111111-1111-1111-1111-111111111111',
                 'youtube:anon-playlist', 'anon-hash')$sql$,
    '42501', null,
    'anonymous cannot insert playlists'
);
select throws_ok(
    $sql$update public.playlists
             set title = 'changed'
           where id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'$sql$,
    '42501', null,
    'anonymous cannot update playlists'
);
select throws_ok(
    $sql$delete from public.playlists
           where id = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'$sql$,
    '42501', null,
    'anonymous cannot delete playlists'
);

-- playlist_items
select throws_ok(
    $sql$select * from public.playlist_items$sql$,
    '42501', null,
    'anonymous cannot select playlist_items'
);
select throws_ok(
    $sql$insert into public.playlist_items (playlist_id, position)
         values ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 100)$sql$,
    '42501', null,
    'anonymous cannot insert playlist_items'
);
select throws_ok(
    $sql$update public.playlist_items
             set status = 'ready'
           where id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'$sql$,
    '42501', null,
    'anonymous cannot update playlist_items'
);
select throws_ok(
    $sql$delete from public.playlist_items
           where id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'$sql$,
    '42501', null,
    'anonymous cannot delete playlist_items'
);

-- admin_audit_log
select throws_ok(
    $sql$select * from public.admin_audit_log$sql$,
    '42501', null,
    'anonymous cannot select admin_audit_log'
);
select throws_ok(
    $sql$insert into public.admin_audit_log (action)
         values ('anon.write')$sql$,
    '42501', null,
    'anonymous cannot insert admin_audit_log'
);
select throws_ok(
    $sql$update public.admin_audit_log
             set action = 'changed'
           where id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'$sql$,
    '42501', null,
    'anonymous cannot update admin_audit_log'
);
select throws_ok(
    $sql$delete from public.admin_audit_log
           where id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'$sql$,
    '42501', null,
    'anonymous cannot delete admin_audit_log'
);

reset role;

select * from finish();

rollback;
