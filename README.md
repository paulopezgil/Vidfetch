# Vidfetch

A polished, desktop-first web application that provides a modern graphical
interface for downloading individual videos and entire playlists. Powered by
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp) as its download engine.

Built with **React + TypeScript + Tailwind CSS** (frontend) and **FastAPI**
(backend), shipped as a single **Docker** container.

> ⚠️ **Legal notice.** This tool is a frontend for yt-dlp. Only download content
> you are authorized to download. You are responsible for complying with
> applicable laws, platform terms of service, and the rights of content owners.

---

## Features

- Inspect a **single video** or an entire **playlist** before downloading.
- Choose **Best quality**, **720p** (when available), or **MP3 audio-only**
  output, with optional subtitle embedding.
- Live **progress tracking** via Server-Sent Events (per-video and
  aggregate playlist progress — "video 8 of 24").
- Automatic **ZIP packaging** of playlist downloads.
- A browsable **media library** (individual files and playlists), with
  download and delete actions.
- Persistent **download history** (SQLite) with retry support.
- Honest error handling for failures, cancellation, and missing files.
- A Material Design 3 interface seeded from YouTube red, with light and dark
  color schemes and adaptive navigation — navigation bar on compact windows,
  a rail on medium windows, and a permanent drawer on expanded windows.

---

## Prerequisites

- **Docker** and **Docker Compose** (v2 or later).

Everything else (Python 3.11, Node.js 22, FFmpeg) is provided by the image.

---

## Quick start

```bash
docker-compose up --build
```

Then open **http://localhost:8000** in your browser.

The image verifies its runtime on startup (`node --version`, FFmpeg) and fails
clearly if a required dependency is missing.

To run in the background:

```bash
docker-compose up --build -d
```

To stop:

```bash
docker-compose down
```

---

## Configuration

Environment variables (see `docker-compose.yml`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOWNLOAD_DIR` | `/app/downloads` | Where media files, ZIPs, and thumbnails live. |
| `DATA_DIR` | `/app/data` | Where the SQLite database lives. |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Maximum simultaneous downloads. |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins. |
| `FRONTEND_DIST` | `/app/frontend-dist` | Built frontend assets (set by the image). |

### Persistent storage

Two bind mounts persist data across container restarts:

- `./downloads` → media files, playlist ZIP archives, and cached thumbnails.
- `./data` → the SQLite database (`yt-dlp.db`), holding task history and
  playlist metadata.

---

## How downloads and ZIP packaging work

- **Single video:** the file is downloaded into the output directory and shown
  in the library.
- **Playlist:** each item is downloaded individually (per-item status is
  tracked), and successfully downloaded items are packaged into a ZIP archive.
  The individual files **and** the ZIP are retained — so you can grab a single
  video or the whole archive.
- **Storage policy:** nothing is deleted after packaging. A valid archive is
  never regenerated automatically; it is only rebuilt when new items are added
  or when you request a rebuild from the playlist detail view.
- Deleting a file removes it from disk but **keeps its history record**. Files
  deleted from a playlist can be re-downloaded at any time.

---

## Updating yt-dlp and the JavaScript runtime

`yt-dlp` changes frequently (YouTube extractors in particular). Rebuild the
image to pick up the latest release:

```bash
docker-compose build --no-cache
docker-compose up -d
```

To update `yt-dlp` without a full image rebuild, run inside a running container:

```bash
docker-compose exec app pip install -U yt-dlp
```

The Node.js runtime is fixed by the image (`node:22`). To change it, update the
`setup_22.x` reference in the `Dockerfile` and rebuild.

---

## Troubleshooting

### YouTube HTTP 403 errors

A 403 from YouTube usually means bot detection, rate limiting, or missing
authentication — not necessarily a missing runtime. Installing Node.js alone
does **not** eliminate all YouTube 403 errors. If you see a 403:

1. **Retry later** — rate limiting and IP reputation are common causes.
2. **Update yt-dlp** — extractors change often; see above.
3. **Use a different IP/network** (e.g., VPN) if your IP is flagged.
4. **Provide cookies** if you have an account (advanced): create a
   `cookies.txt` and configure yt-dlp to use it. This image does **not** bundle
   cookies or credentials — add your own if you need them.

The backend surfaces a human-readable message for 403s so failures are not
silent.

### Missing runtime dependencies

The container verifies `node --version` at startup and fails if Node is absent.
FFmpeg availability is reported on the **Settings** page and at `/api/health`.
Audio extraction (MP3) and media merging require FFmpeg.

### Checking health

```
curl http://localhost:8000/api/health
```

---

## Known limitations

- Playlist item thumbnails use a placeholder (only the playlist thumbnail and
  single-video thumbnails are cached).
- Progress is streamed for active tasks; completed tasks are persisted to
  history. Tasks interrupted by a restart are marked as failed.
- Cancellation is best-effort: an in-progress network transfer may finish its
  current chunk before the task is torn down.
- Large playlists download sequentially per item (bounded by
  `MAX_CONCURRENT_DOWNLOADS`).

---

## Running tests

Backend unit tests (requires Python 3.11+ and the dev dependencies):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest backend/tests
```

---

## Project structure

```
backend/                 FastAPI application
  main.py                app entry point + SPA serving
  config.py              environment configuration
  database.py            SQLite storage (tasks, playlists, items)
  models/schemas.py      Pydantic request/response models
  routers/               API endpoints (info, download, tasks, files, history, playlists, health)
  services/              yt-dlp, task manager, ZIP, library logic
  tests/                 unit tests
frontend/                React + Vite + TypeScript + Tailwind
  src/pages/             Dashboard, Library, PlaylistDetail, History, Settings
  src/components/        reusable UI components
Dockerfile               multi-stage build
docker-compose.yml       local orchestration + persistent volumes
```

---

## License

Released under the [MIT License](LICENSE). Provided as-is; you are responsible
for using it lawfully.
