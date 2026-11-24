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

### Still in progress for this release

- Four-tab shell (Home, Tracks, Playlists, Artists & Albums) and the persistent
  player bar.
- Date-grouped Tracks browsing, search, and per-track `•••` menus.
- User-created playlists, metadata editing, and cover uploads.
- Offline-first client storage, two-phase downloads, and the sync engine.
- Offline/multi-device hardening and performance work.
