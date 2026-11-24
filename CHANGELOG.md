# Changelog

All notable changes to Vidfetch are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases follow
Semantic Versioning and are cut from `main`.

## [Unreleased] — v2.3.0

Target release for the Spotify-style navigation and personal-library rewrite.
This section accumulates the change groups as they land on `dev`.

### Added

- **Per-user track model.** A `user_tracks` row is the user's own library entry
  for a shared media asset. It stores editable title, artist, album, and cover
  fields while the file itself stays a single global cache entry. Rows are
  created automatically when a download becomes ready and were backfilled for
  existing downloads.
- **`GET /api/tracks`.** Owner-scoped, paginated list of visible tracks with
  resolved titles and user metadata. It preserves the existing library rules:
  hidden downloads and non-ready assets do not appear, multiple ready jobs for
  one asset collapse into a single track, and the newest download comes first.
- **Tracks destination.** The former Library page now reads the tracks API and
  exposes the same download strip, filters, playlists, preview, delete, and
  pagination behavior. Track rows show artist and album when they are set.

### Changed

- The sidebar destination "Biblioteca" is now "Tracks" (`/tracks`).
- `/library` redirects to `/tracks`; playlist detail keeps its existing route
  until the navigation restructure lands.
- Playlist-detail back links now return to Tracks.

### Database

- Added migration `20261124120000_user_tracks.sql` (rendered from
  `supabase/templates/`), including the `user_tracks` table, metadata indexes,
  the `updated_at` trigger, the download-to-track trigger, the backfill, RLS,
  and the service-role grant.
- Extended the pgTAP application-table RLS coverage to `user_tracks`.

### Verification

- Backend: `python3 -m pytest backend/tests -q` → 531 passed.
- Mutation check: breaking the `library_hidden = false` visibility predicate
  fails `test_list_tracks_scopes_visibility_and_orders_newest_downloaded_first`.
- Frontend: `npm run build` green; preview serves `/` and `/tracks` with HTTP 200.
- Live local stack: `GET /api/tracks` returns the backfilled track with
  `status: "ready"`; unauthenticated requests get 401.

### Roadmap and progress

The release is delivered as six change groups, all targeting this single
`v2.3.0` release. Overall progress: **1 of 6 complete**.

| # | Change group | Frontend | Backend | Status |
| --- | --- | --- | --- | --- |
| 1 | **Per-user track model** | Tracks page reads the new API | `user_tracks` table, backfill/trigger, `GET /api/tracks` | ✅ Done |
| 2 | **New shell + player** | Four-tab navigation (Home, Tracks, Playlists, Artists & Albums); Home focuses on import and active downloads; persistent player bar with queue | Minor player/session state; signed stream URLs already exist | ⬜ Planned |
| 3 | **Browse views** | Date-grouped Tracks, quick search, `•••` track menus; Artists/Albums cards and drill-down | Read endpoints for grouped artist/album views | ⬜ Planned |
| 4 | **Playlists + metadata editing** | User playlist grid/detail/reorder; Edit Details modal; artist/album autocomplete; cover upload | User playlist CRUD and ordering; metadata updates; cover storage; per-user isolation | ⬜ Planned |
| 5 | **Offline-first + two-phase download** | Local IndexedDB metadata and media cache; offline playback; queued mutations and sync status | Sync/push endpoints, `updated_at` + last-write-wins, tombstones, idempotent replay, per-device state | ⬜ Planned |
| 6 | **Hardening** | Offline and multi-device QA, storage limits, accessibility and performance | Backfill verification, conflict/race tests, quota handling | ⬜ Planned |

Group 1 is the foundation the remaining groups build on: track identity, custom
metadata fields, and the owner-scoped read path are already in place on `dev`.

