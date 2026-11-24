-- Application schema bootstrap for a standard PostgreSQL database.
--
-- There are no Supabase-managed schemas or client roles anymore. The backend
-- owns every table in this schema and is the only component that connects.

create schema if not exists "public";
