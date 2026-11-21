-- Per-user library visibility.
--
-- Removing an item from a user's library must not delete a shared media asset
-- or erase download history. The library filters on this flag; history keeps
-- the row.

alter table public.download_jobs
    add column if not exists library_hidden boolean not null default false;

create index if not exists download_jobs_user_library_idx
    on public.download_jobs (user_id, library_hidden, created_at desc)
    where status = 'ready';
