# Changelog

All notable changes to Vidfetch are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); releases follow
Semantic Versioning and are cut from `main`.

## [v2.5.3] — 2026-11-27

Patch release restoring legacy playlist tracks and fixing mixed-media pagination.

### Fixed

- **Older playlists never reached Songs.** Ready playlist items from before the
  per-item job pipeline had no linked `download_jobs` row, so no `user_tracks`
  row existed. A new migration backfills one terminal `playlist_item` job per
  ready item that lacks one, links it to the item, and lets the existing trigger
  create the missing track with the playlist title and item channel.
- **Songs/Videos hid tracks behind mixed pages.** `/api/tracks` now accepts
  `kind=audio|video|image` and filters in SQL. Songs and Videos request their own
  media kind, so a page full of videos can no longer make the Songs tab look
  empty (or skew its totals/pagination).

## [v2.5.2] — 2026-11-27

Patch release for offline list artwork and cached playlist details.

### Fixed

- **Offline list artwork.** Songs, imported playlists and artist rows now prefer
  the stored signed `thumbnail_url` instead of forcing a fresh media-token
  request. The thumbnail component also retries when the source changes, so an
  image that failed once offline can render when its cached URL arrives.
- **Imported playlists did not open offline.** The Playlists page now warms each
  imported playlist detail into the IndexedDB response cache while online.
  Cached playlist payloads are normalized defensively, and an uncached playlist
  shows a specific “not available offline” state instead of a render error.

### Added

- **Signed playlist-item thumbnails.** `GET /api/playlists/{id}` now returns a
  signed `thumbnail_url` for each item whose asset has a cached thumbnail, so
  imported playlist rows keep their artwork offline.

## [v2.5.1] — 2026-11-27

Patch release adding the self-service password change form.

### Added

- **Self-service password change.** Settings now has a **Seguretat** section
  where a signed-in user can replace a temporary/admin-reset password with
  their own. It validates the current password, the new password and the
  confirmation, keeps the current session, and revokes the user's other
  sessions through the existing `/api/auth/password` endpoint.

## [v2.5.0] — 2026-11-27

Minor release adding the administrator password-reset workflow.

### Added

- **Administrator password reset.** The admin user list now has a per-account
  **Restableix la contrasenya** action. An admin can enter or generate a strong
  temporary password, which is shown exactly once; the reset revokes every
  session for that account and writes a secret-free `reset_password` row to the
  admin audit log.

## [v2.4.3] — 2026-11-27

Patch release for airplane-mode offline recovery and safe PWA updates.

### Fixed

- **Airplane-mode black screen after a service-worker update.** The shell now
  ships a build-time `precache-manifest.json` with every emitted chunk, and the
  service worker precaches all of them during install. Lazy route chunks are
  therefore available offline, not just the entry bundle.
- **Unsafe service-worker takeover.** Automatic `skipWaiting()`/`clients.claim()`
  removed: the old worker keeps the old shell and hashed assets until every old
  client closes, so an update can no longer delete the cache under a running
  page.
- **Blank-screen recovery.** `index.html` now carries an inline boot fallback
  with a spinner and a delayed “Recarrega” action, and the React tree is wrapped
  in an inline-styled error boundary.

## [v2.4.2] — 2026-11-27

Patch release for offline icon/artwork caching and the player-bar title action.

### Added

- **Offline font and image cache.** The Material Symbols icon font, Roboto,
  thumbnails and covers are cached locally. The service worker now handles
  Google Fonts and image requests from any origin, with signed-image cache keys
  normalized to `origin + pathname` so tokens and CDN parameters can change.
  Saved media also warms its thumbnail cache.

### Fixed

- **Offline icons and images disappearing on iOS.** The app shell could render
  while the icon font and artwork vanished because those requests were not in
  Cache Storage. They now survive a network drop after one online load.
- **Player-bar title did not maximize.** Clicking the song title/credit in the
  docked player now opens the full-screen now-playing view, with the same
  keyboard and ARIA behaviour as the artwork button.

## [v2.4.1] — 2026-11-27

Patch release for the profile-menu navigation move and the iOS safe-area
bottom-bar fix.

### Changed

- **Information and settings live in the profile menu.** The `Informació`
  installation guide and `Configuració` moved out of the bottom/rail/drawer
  navigation, leaving only the five listening destinations. The install page is
  now presented as **Informació** with the installation guide inside it.

### Fixed

- **iOS bottom navigation clipping.** The compact navigation height now includes
  `env(safe-area-inset-bottom)` and the tab links no longer hide overflow, so
  icons and labels fit inside the iPhone home-indicator area instead of being
  cut in half.

## [v2.4.0] — 2026-11-26

Release focused on playlist correctness, incremental library delivery,
failed-download isolation, curated playlist sharing, and the PWA install guide.

### Added

- **Per-playlist-item jobs and incremental library delivery.** Every finished
  playlist item is recorded immediately as its own terminal `playlist_item`
  job. Ready items create the owner's `user_tracks` row at once, so completed
  songs appear in Songs/Videos while the rest of the playlist is still
  downloading. Failed items stay asset-less and never seed a track.
- **Playlist metadata defaults.** Playlist items inherit the playlist title as
  their album and each video's own channel as their artist; single-video jobs
  use the source channel as the artist. The track trigger only fills blank
  artist/album fields, so later downloads never overwrite user edits.
- **Curated playlist sharing.** Owners can share a curated playlist with another
  approved account by email, list/revoke recipients, and shared users get a
  read-only detail view plus playback and file download. New
  `user_playlist_shares` table and `/api/user-playlists/shared` and
  `/{id}/shares` endpoints.
- **Signed track thumbnail URLs.** `/api/tracks` and curated-playlist details
  now expose a signed `thumbnail_url` for each asset, bound to the viewer.
- **Artists/Albums group editing.** Album and artist drill-downs can rename the
  group and, for albums, update the artist across every track in one action.
- **Full Catalan interface copy.** Remaining English labels, dialogs, status
  text, error fallbacks, and the navigation destinations were translated.
- **PWA install guide tab.** A new `Instal·la` destination explains how to
  install Vidfetch from the browser, with a segmented switch for Android,
  iPhone, and desktop and Catalan step-by-step instructions for each.

### Fixed

- **Playlist items missing from Songs/Videos.** The library no longer excludes
  tracks whose representative job has a `playlist_id`; media type decides the
  destination.
- **Failed downloads leaking into the library and UI.** Failed jobs are shown
  only in the Home `Descàrregues fallides` section with a generic message. Raw
  backend error text is no longer rendered in `JobCard` or imported playlist
  rows, and failed items are hidden from the playlist item list.
- **Playlist progress stalling until completion.** Ready items are now exposed
  as soon as they finish instead of after the whole playlist run.
- **Missing player artwork.** The mini player and maximized player resolve
  artwork from the custom cover, the signed track thumbnail, or the media
  token, including offline copies.
- **Three-dot menus shifting songs.** Overflow menus now render through a body
  portal with fixed positioning and `preventScroll` focus, so they overlay the
  list and never move or clip the row.
- **Server processing labelled as a download.** The job card now says
  "Preparant"/"S'està preparant el fitxer al servidor…" for server-side work;
  user file actions remain "Descarrega".
- **Logo disappearing offline.** The app mark is inline SVG and the service
  worker precaches/cache-first serves the public brand assets.
- **Artists destination looked like a user profile.** The navigation
  destination and artist cards now use disc/music iconography and album art.

### Changed

- Added the now-playing equalizer indicator to Songs, imported playlist,
  curated playlist, Artists/Albums, and add-tracks rows, replacing the
  redundant ready/active chip in library rows.
- Enlarged the compact bottom navigation bar and its icon/label targets.
- `Artists & Albums` is now `Artistes i àlbums`, `Playlists` is `Llistes`, and
  `Home` is `Inici`.

### Database

- Added `db/migrations/00000000000002_track_metadata_and_sharing.sql` and its
  template: `download_jobs.artist`/`album`, `playlist_items.channel`, the
  `user_playlist_shares` table, and the metadata-aware user-track trigger.

### Verification

- Backend with real PostgreSQL: `865 passed` (`TEST_DATABASE_URL` against a
  migrated throwaway database); `python3 -c "import backend.app.main"` OK.
- Frontend production build: green, zero TypeScript errors; `/install` served
  with HTTP 200 in preview.
- Browser E2E: downloaded a 19-item MP3 playlist and watched items appear in
  Songs incrementally before the playlist finished; confirmed artist/album
  metadata; confirmed a deliberately failed download appeared only in Home with
  generic copy and no library track; confirmed Songs/Videos separation.
- Browser E2E: menu overlay did not move the row; equalizer and player artwork
  rendered; shared a curated playlist with a second approved account, saw it in
  `Compartides amb mi`, and played it read-only; edited an album group across
  19 tracks and restored the original name.

## [v2.3.0] — 2026-11-24

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

