-- RLS and auth-user trigger coverage for public.profiles.
--
-- Run with:
--   supabase start
--   supabase test db
--
-- The Supabase CLI enables pgTAP before running this file, so only plan(),
-- assertions, and finish() are needed here. Everything is rolled back.

begin;

select plan(14);

-- ---------------------------------------------------------------------------
-- Fixtures (as the postgres role)
-- ---------------------------------------------------------------------------

-- The auth.users trigger creates the matching profiles rows.
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
values
    (
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
    ),
    (
        '00000000-0000-0000-0000-000000000000',
        '22222222-2222-2222-2222-222222222222',
        'authenticated',
        'authenticated',
        'bob@example.com',
        now(),
        now(),
        now(),
        '{"provider":"email","providers":["email"]}'::jsonb,
        '{}'::jsonb
    );

select is(
    (select count(id)::int from public.profiles),
    2,
    'auth.users insert trigger created one profile per user'
);

-- ---------------------------------------------------------------------------
-- Authenticated user: alice
-- ---------------------------------------------------------------------------

set local role authenticated;
set local request.jwt.claims =
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}';

select is(
    (select count(id)::int from public.profiles),
    1,
    'authenticated user sees exactly one profile row'
);

select is(
    (select email from public.profiles
      where id = '11111111-1111-1111-1111-111111111111'),
    'alice@example.com',
    'authenticated user can select their own profile'
);

select is(
    (select count(id)::int from public.profiles
      where id = '22222222-2222-2222-2222-222222222222'),
    0,
    'authenticated user cannot select another user profile'
);

select throws_ok(
    $sql$update public.profiles
             set is_approved = true
           where id = '11111111-1111-1111-1111-111111111111'$sql$,
    '42501',
    null,
    'authenticated user cannot approve their own profile'
);

select throws_ok(
    $sql$update public.profiles
             set app_role = 'admin'
           where id = '11111111-1111-1111-1111-111111111111'$sql$,
    '42501',
    null,
    'authenticated user cannot promote their own profile'
);

select throws_ok(
    $sql$insert into public.profiles (id, email)
         values ('33333333-3333-3333-3333-333333333333', 'mallory@example.com')$sql$,
    '42501',
    null,
    'authenticated user cannot insert a profile'
);

select throws_ok(
    $sql$delete from public.profiles
           where id = '11111111-1111-1111-1111-111111111111'$sql$,
    '42501',
    null,
    'authenticated user cannot delete a profile'
);

-- ---------------------------------------------------------------------------
-- Anonymous client
-- ---------------------------------------------------------------------------

reset role;
set local role anon;
set local request.jwt.claims = '{"role":"anon"}';

select throws_ok(
    $sql$select id from public.profiles$sql$,
    '42501',
    null,
    'anonymous client cannot select profiles'
);

select throws_ok(
    $sql$update public.profiles
             set email = 'attacker@example.com'$sql$,
    '42501',
    null,
    'anonymous client cannot update profiles'
);

-- ---------------------------------------------------------------------------
-- auth.users -> profiles trigger
-- ---------------------------------------------------------------------------

reset role;
set local request.jwt.claims = '{}';

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
    '33333333-3333-3333-3333-333333333333',
    'authenticated',
    'authenticated',
    'charlie@example.com',
    now(),
    now(),
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    '{}'::jsonb
);

select is(
    (select email from public.profiles
      where id = '33333333-3333-3333-3333-333333333333'),
    'charlie@example.com',
    'auth.users insert trigger creates a profile'
);

select is(
    (select is_approved from public.profiles
      where id = '33333333-3333-3333-3333-333333333333'),
    false,
    'new profiles start unapproved'
);

select is(
    (select app_role from public.profiles
      where id = '33333333-3333-3333-3333-333333333333'),
    'user',
    'new profiles start with the user role'
);

update auth.users
   set email = 'charlie+renamed@example.com'
 where id = '33333333-3333-3333-3333-333333333333';

select is(
    (select email from public.profiles
      where id = '33333333-3333-3333-3333-333333333333'),
    'charlie+renamed@example.com',
    'auth.users email update synchronizes profiles.email'
);

select * from finish();

rollback;
