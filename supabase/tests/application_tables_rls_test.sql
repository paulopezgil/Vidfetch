-- RLS coverage for the v2 application tables that must have no direct client
-- access: media_assets, download_jobs, playlists, playlist_items,
-- user_tracks, user_playlists, user_playlist_tracks, and admin_audit_log.
--
-- Run with:
--   supabase start
--   supabase test db
--
-- The Supabase CLI enables pgTAP before running this file. Everything is
-- rolled back, including the fixture rows.

begin;

select plan(66);

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

insert into public.user_tracks (id, user_id, asset_id)
values (
    'ffffffff-ffff-ffff-ffff-ffffffffffff',
    '11111111-1111-1111-1111-111111111111',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
);

insert into public.user_playlists (id, user_id, name)
values (
    '99999999-9999-9999-9999-999999999999',
    '11111111-1111-1111-1111-111111111111',
    'Test playlist'
);

insert into public.user_playlist_tracks (playlist_id, user_track_id, position)
values (
    '99999999-9999-9999-9999-999999999999',
    'ffffffff-ffff-ffff-ffff-ffffffffffff',
    0
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
               'user_tracks',
               'user_playlists',
               'user_playlist_tracks',
               'admin_audit_log'
           )
           and c.relrowsecurity
    ),
    8,
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
               'user_tracks',
               'user_playlists',
               'user_playlist_tracks',
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

-- user_tracks
select throws_ok(
    $sql$select * from public.user_tracks$sql$,
    '42501', null,
    'authenticated cannot select user_tracks'
);
select throws_ok(
    $sql$insert into public.user_tracks (user_id, asset_id)
         values ('11111111-1111-1111-1111-111111111111',
                 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')$sql$,
    '42501', null,
    'authenticated cannot insert user_tracks'
);
select throws_ok(
    $sql$update public.user_tracks
             set custom_title = 'changed'
           where id = 'ffffffff-ffff-ffff-ffff-ffffffffffff'$sql$,
    '42501', null,
    'authenticated cannot update user_tracks'
);
select throws_ok(
    $sql$delete from public.user_tracks
           where id = 'ffffffff-ffff-ffff-ffff-ffffffffffff'$sql$,
    '42501', null,
    'authenticated cannot delete user_tracks'
);

-- user_playlists
select throws_ok(
    $sql$select * from public.user_playlists$sql$,
    '42501', null,
    'authenticated cannot select user_playlists'
);
select throws_ok(
    $sql$insert into public.user_playlists (user_id, name)
         values ('11111111-1111-1111-1111-111111111111', 'Direct')$sql$,
    '42501', null,
    'authenticated cannot insert user_playlists'
);
select throws_ok(
    $sql$update public.user_playlists
             set name = 'changed'
           where id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'authenticated cannot update user_playlists'
);
select throws_ok(
    $sql$delete from public.user_playlists
           where id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'authenticated cannot delete user_playlists'
);

-- user_playlist_tracks
select throws_ok(
    $sql$select * from public.user_playlist_tracks$sql$,
    '42501', null,
    'authenticated cannot select user_playlist_tracks'
);
select throws_ok(
    $sql$insert into public.user_playlist_tracks (playlist_id, user_track_id, position)
         values ('99999999-9999-9999-9999-999999999999',
                 'ffffffff-ffff-ffff-ffff-ffffffffffff', 1)$sql$,
    '42501', null,
    'authenticated cannot insert user_playlist_tracks'
);
select throws_ok(
    $sql$update public.user_playlist_tracks
             set position = 5
           where playlist_id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'authenticated cannot update user_playlist_tracks'
);
select throws_ok(
    $sql$delete from public.user_playlist_tracks
           where playlist_id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'authenticated cannot delete user_playlist_tracks'
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

-- user_tracks
select throws_ok(
    $sql$select * from public.user_tracks$sql$,
    '42501', null,
    'anonymous cannot select user_tracks'
);
select throws_ok(
    $sql$insert into public.user_tracks (user_id, asset_id)
         values ('11111111-1111-1111-1111-111111111111',
                 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')$sql$,
    '42501', null,
    'anonymous cannot insert user_tracks'
);
select throws_ok(
    $sql$update public.user_tracks
             set custom_title = 'changed'
           where id = 'ffffffff-ffff-ffff-ffff-ffffffffffff'$sql$,
    '42501', null,
    'anonymous cannot update user_tracks'
);
select throws_ok(
    $sql$delete from public.user_tracks
           where id = 'ffffffff-ffff-ffff-ffff-ffffffffffff'$sql$,
    '42501', null,
    'anonymous cannot delete user_tracks'
);

-- user_playlists
select throws_ok(
    $sql$select * from public.user_playlists$sql$,
    '42501', null,
    'anonymous cannot select user_playlists'
);
select throws_ok(
    $sql$insert into public.user_playlists (user_id, name)
         values ('11111111-1111-1111-1111-111111111111', 'Direct')$sql$,
    '42501', null,
    'anonymous cannot insert user_playlists'
);
select throws_ok(
    $sql$update public.user_playlists
             set name = 'changed'
           where id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'anonymous cannot update user_playlists'
);
select throws_ok(
    $sql$delete from public.user_playlists
           where id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'anonymous cannot delete user_playlists'
);

-- user_playlist_tracks
select throws_ok(
    $sql$select * from public.user_playlist_tracks$sql$,
    '42501', null,
    'anonymous cannot select user_playlist_tracks'
);
select throws_ok(
    $sql$insert into public.user_playlist_tracks (playlist_id, user_track_id, position)
         values ('99999999-9999-9999-9999-999999999999',
                 'ffffffff-ffff-ffff-ffff-ffffffffffff', 1)$sql$,
    '42501', null,
    'anonymous cannot insert user_playlist_tracks'
);
select throws_ok(
    $sql$update public.user_playlist_tracks
             set position = 5
           where playlist_id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'anonymous cannot update user_playlist_tracks'
);
select throws_ok(
    $sql$delete from public.user_playlist_tracks
           where playlist_id = '99999999-9999-9999-9999-999999999999'$sql$,
    '42501', null,
    'anonymous cannot delete user_playlist_tracks'
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
