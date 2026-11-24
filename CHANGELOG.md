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
- **Four-tab shell and persistent player.** Home, Tracks, Playlists, and
  Artists & Albums are top-level destinations. A Spotify-style player bar is
  docked across every approved route with a queue, auto-advance, seek, volume,
  signed-URL refresh, and a play action on track rows.
- **Playlists page.** A responsive grid of the user's imported playlists with
  cover, channel, and item count, linking into the playlist detail view.
- **Artists & Albums page.** A toggle between artist and album groupings built
  from track metadata, with circular artist cards, album cards, and per-card
  track drill-downs.
- **Tracks search and date grouping.** A quick search bar filters tracks
  server-side by title, artist, or album. The individual track list is grouped
  by download day (Avui, Ahir, then each calendar date), with the existing
  media filters applied before grouping and imported playlist cards filtered
  locally while a search is active.
- **Track editing and cover art.** A per-row `•••` menu opens an M3 Edit Details
  dialog for title, artist, and album (with debounced autocomplete from the
  user's existing values) and a JPEG/PNG/WebP cover upload, served through
  short-lived signed URLs.
- **Curated playlists.** Users can create playlists, add tracks from the track
  menu, reorder them with up/down controls, remove tracks, play the playlist,
  rename it, and delete it. Playlists show a four-tile cover collage and a live
  track count, and imported source playlists are listed separately.

### Changed

- The sidebar destination "Biblioteca" is now "Tracks" (`/tracks`), and the
  in-app home label is now "Home".
- `/library` redirects to `/tracks`; `/library/playlist/:id` redirects to
  `/imported/:id`.
- Curated playlists live at `/playlists/:id`; imported source playlists moved to
  `/imported/:id`, and their back links return to `/playlists`.

### Database

- Added migration `20261124120000_user_tracks.sql` (rendered from
  `supabase/templates/`), including the `user_tracks` table, metadata indexes,
  the `updated_at` trigger, the download-to-track trigger, the backfill, RLS,
  and the service-role grant.
- Extended the pgTAP application-table RLS coverage to `user_tracks`.
- Added migration `20261124180000_user_playlists.sql` for curated playlists and
  their ordered membership, including deferred position uniqueness, RLS, and
  service-role grants; pgTAP coverage extended to both tables.

### Verification

- Backend: `python3 -m pytest backend/tests -q` → 629 passed.
- Mutation check: breaking the `library_hidden = false` visibility predicate
  fails `test_list_tracks_scopes_visibility_and_orders_newest_downloaded_first`;
  removing the artist/album search predicates fails the matching search tests;
  weakening the reorder permutation guard fails
  `test_reorder_tracks_rejects_orders_that_are_not_a_permutation`;
  disabling magic-byte matching fails the cover validation tests.
- Frontend: `npm run build` green; preview serves the shell routes with HTTP 200.
- Shell: build green; preview serves `/`, `/tracks`, `/playlists`, `/artists`,
  and detail routes with HTTP 200; navigation exposes exactly the four
  destinations plus Admin.
- Live local stack: `GET /api/tracks` returns the backfilled track with
  `status: "ready"`; unauthenticated requests get 401. Searching
  `q=DESMONTANDO` returns it, `q=zzz-no-match` returns 0, and a whitespace-only
  `q` behaves as no filter.
- Browser E2E: edited a track’s title/artist/album, uploaded a 64×64 PNG cover,
  saw the row and Artists view update, then restored the original metadata and
  removed the cover. Created a curated playlist, added the track from the `•••`
  menu, played the playlist, removed the track, and deleted the playlist.

### Roadmap and progress

The release is delivered as six change groups, all targeting this single
`v2.3.0` release. Overall progress: **4 of 6 complete**.

| # | Change group | Frontend | Backend | Status |
| --- | --- | --- | --- | --- |
| 1 | **Per-user track model** | Tracks page reads the new API | `user_tracks` table, backfill/trigger, `GET /api/tracks` | ✅ Done |
| 2 | **New shell + player** | Four-tab navigation (Home, Tracks, Playlists, Artists & Albums); Home focuses on import and active downloads; persistent player bar with queue | Minor player/session state; signed stream URLs already exist | ✅ Done |
| 3 | **Browse views** | Date-grouped Tracks with quick search; Artists/Albums cards and drill-down | Server-side search over resolved title, artist, and album | ✅ Done |
| 4 | **Playlists + metadata editing** | User playlist grid/detail/reorder; track `•••` menu; Edit Details modal; artist/album autocomplete; cover upload | User playlist CRUD and ordering; metadata updates; cover storage; per-user isolation | ✅ Done |
| 5 | **Offline-first + two-phase download** | Local IndexedDB metadata and media cache; offline playback; queued mutations and sync status | Sync/push endpoints, `updated_at` + last-write-wins, tombstones, idempotent replay, per-device state | ⬜ Planned |
| 6 | **Hardening** | Offline and multi-device QA, storage limits, accessibility and performance | Backfill verification, conflict/race tests, quota handling | ⬜ Planned |

Group 1 is the foundation the remaining groups build on: track identity, custom
metadata fields, and the owner-scoped read path are already in place on `dev`.
Group 2 adds the navigation shell the rest of the release hangs off, group 3
turns the Tracks and Artists/Albums destinations into browsable views, and
group 4 adds the editing, cover, and curated-playlist workflows.

