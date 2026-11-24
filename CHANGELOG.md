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
- **Playlist picker.** A dedicated `/playlists/:id/add` view (not in the sidebar)
  reuses the Tracks layout with only one control per row: add when the song is
  not in the playlist, check when it is. Playlist detail links straight to it.
- **Offline metadata.** Library, playlist, and facet reads are cached in
  IndexedDB and served when the network is down. Track metadata, cover, and
  curated-playlist edits queue locally and replay FIFO on reconnect, with an
  offline banner, pending count, and an offline-capable profile boot.
- **Offline media and two-phase downloads.** Completed audio jobs transfer to
  the device automatically into Cache Storage. The player prefers the local
  blob, the production service worker serves the app shell offline, and each
  song shows a cloud → spinner → check save control. Saved songs are permanent:
  there is no per-song or bulk un-download action.
- **Account menu.** A top-bar avatar (Google image or initials) opens the
  account menu with the email/role, **Canvia de compte**, **Tanca la sessió**,
  and an admin shortcut. Sign-out clears the cached responses, pending offline
  queue, and per-user profile, while keeping saved media.
- **Hardening.** A read-only offline storage overview (usage, quota, persistence
  state), queue cap (200), quota-error cleanup, permanent-save semantics,
  route-level code splitting (24 chunks), skip link, dialog focus handling, and
  reduced-motion support.

### Changed

- The sidebar destination "Biblioteca" is now "Tracks" (`/tracks`), and the
  in-app home label is now "Home".
- `/library` redirects to `/tracks`; `/library/playlist/:id` redirects to
  `/imported/:id`.
- Curated playlists live at `/playlists/:id`; imported source playlists moved to
  `/imported/:id`, and their back links return to `/playlists`.
- Per-song download buttons are replaced by the offline save control; video and
  image files keep their download buttons and playlist ZIP export is unchanged.
- Saved songs cannot be un-downloaded; the check state is a permanent status
  indicator and the storage dialog is read-only.
- Download activity now appears only on Home (active and recently finished),
  never in Tracks.

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

- Backend: `python3 -m pytest backend/tests -q` → 699 passed (baseline 629;
  70 new hardening cases).
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
- Offline E2E: saved a 33.7 MB song (Cache Storage + IndexedDB verified), saw a
  newly finished audio job transfer automatically, then stopped the backend and
  played the saved song with **zero** `/api/media` requests. The saved state is
  permanent and has no removal affordance.
- Offline metadata E2E: with the transport blocked, cached tracks rendered, a
  track edit and playlist rename queued, reconnect flushed both in order, and
  the profile/session booted the shell offline.
- Playlist picker E2E: `/playlists/:id/add` showed only add/check controls,
  adding flipped the row to check and the count to 1, removing flipped it back,
  and playlist detail exposed **Afegeix tracks**.
- Service worker: production preview kept the app shell (`/login`) rendering
  after the server stopped; cached JS/CSS/manifest were present.
- Backend hardening: per-user isolation, visibility consistency, input limits,
  cover symlink rejection, reorder permutations, error mapping, and schema
  qualification covered; two real defects fixed (cover symlink bypass, playlist
  detail count drift).
- Account E2E: avatar/menu render, logout returns to `/login`, cached responses
  and queue drop to 0 while 2 saved media copies remain, and logging back in
  restores the shell.
- Frontend hardening: 24 JS chunks, `/`, `/tracks`, `/playlists`, `/artists`
  return 200; skip link, dialog focus, and read-only storage dialog verified.

### Roadmap and progress

The release is delivered as six change groups, all targeting this single
`v2.3.0` release. Overall progress: **6 of 6 complete**.

| # | Change group | Frontend | Backend | Status |
| --- | --- | --- | --- | --- |
| 1 | **Per-user track model** | Tracks page reads the new API | `user_tracks` table, backfill/trigger, `GET /api/tracks` | ✅ Done |
| 2 | **New shell + player** | Four-tab navigation (Home, Tracks, Playlists, Artists & Albums); Home focuses on import and active downloads; persistent player bar with queue | Minor player/session state; signed stream URLs already exist | ✅ Done |
| 3 | **Browse views** | Date-grouped Tracks with quick search; Artists/Albums cards and drill-down | Server-side search over resolved title, artist, and album | ✅ Done |
| 4 | **Playlists + metadata editing** | User playlist grid/detail/reorder; track `•••` menu; Edit Details modal; artist/album autocomplete; cover upload | User playlist CRUD and ordering; metadata updates; cover storage; per-user isolation | ✅ Done |
| 5 | **Offline-first + two-phase download** | IndexedDB metadata/media cache, queued edits, offline playback, automatic client transfer, service worker, save-state button | Existing owner-scoped mutations replayed FIFO; `updated_at`/tombstones on track and playlist rows | ✅ Done |
| 6 | **Hardening** | Read-only storage overview, queue cap/quota safety, permanent saves, code splitting, accessibility, reduced motion | 70 isolation/validation/ordering/error-mapping tests; cover symlink and count-drift fixes | ✅ Done |

Group 1 is the foundation the remaining groups build on: track identity, custom
metadata fields, and the owner-scoped read path are already in place on `dev`.
Group 2 adds the navigation shell the rest of the release hangs off, group 3
turns the Tracks and Artists/Albums destinations into browsable views, group 4
adds the editing, cover, and curated-playlist workflows, group 5 makes the
library usable offline with automatic two-phase transfers, and group 6 hardens
storage, accessibility, and the API.

