"""Persistent SQLite storage for task history and playlist metadata.

Uses the standard library ``sqlite3`` in WAL mode. A module-level lock guards
writes; reads open a fresh connection so they can run concurrently with the
single writer. Task records persist across restarts; live progress fields are
kept in memory and written through at status transitions and completion.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Optional

from .config import settings

_write_lock = threading.Lock()


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id            TEXT PRIMARY KEY,
    url                TEXT NOT NULL,
    title              TEXT NOT NULL DEFAULT '',
    video_id           TEXT NOT NULL DEFAULT '',
    operation_type     TEXT NOT NULL,
    format             TEXT NOT NULL DEFAULT 'best',
    embed_subs         INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL,
    progress           REAL NOT NULL DEFAULT 0,
    downloaded_bytes   INTEGER NOT NULL DEFAULT 0,
    total_bytes        INTEGER NOT NULL DEFAULT 0,
    speed              REAL NOT NULL DEFAULT 0,
    eta                REAL NOT NULL DEFAULT 0,
    item_index         INTEGER NOT NULL DEFAULT 0,
    item_count         INTEGER NOT NULL DEFAULT 0,
    completed_items    INTEGER NOT NULL DEFAULT 0,
    current_item_title TEXT NOT NULL DEFAULT '',
    playlist_id        TEXT NOT NULL DEFAULT '',
    output_filename    TEXT NOT NULL DEFAULT '',
    error              TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    completed_at       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS playlists (
    playlist_id     TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    channel         TEXT NOT NULL DEFAULT '',
    thumbnail_path  TEXT NOT NULL DEFAULT '',
    item_count      INTEGER NOT NULL DEFAULT 0,
    total_size      INTEGER NOT NULL DEFAULT 0,
    zip_path        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playlist_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id TEXT NOT NULL,
    item_index  INTEGER NOT NULL,
    video_id    TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    duration    REAL,
    status      TEXT NOT NULL DEFAULT 'pending',
    filename    TEXT NOT NULL DEFAULT '',
    size        INTEGER NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT '',
    UNIQUE(playlist_id, url)
);

CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_playlist ON playlist_items(playlist_id, item_index);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db() -> None:
    settings.ensure_directories()
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _execute(sql: str, params: Any = ()) -> None:
    with _write_lock:
        conn = _connect()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()


def _query(sql: str, params: Any = ()) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _query_one(sql: str, params: Any = ()) -> Optional[dict]:
    rows = _query(sql, params)
    return rows[0] if rows else None


# --------------------------------------------------------------------------- #
# Tasks (history + active task persistence)
# --------------------------------------------------------------------------- #

def insert_task(task: dict) -> None:
    _execute(
        """
        INSERT INTO tasks (
            task_id, url, title, video_id, operation_type, format, embed_subs,
            status, progress, downloaded_bytes, total_bytes, speed, eta,
            item_index, item_count, completed_items, current_item_title,
            playlist_id, output_filename, error, created_at, updated_at, completed_at
        ) VALUES (
            :task_id, :url, :title, :video_id, :operation_type, :format, :embed_subs,
            :status, :progress, :downloaded_bytes, :total_bytes, :speed, :eta,
            :item_index, :item_count, :completed_items, :current_item_title,
            :playlist_id, :output_filename, :error, :created_at, :updated_at, :completed_at
        )
        """,
        task,
    )


def update_task(task: dict) -> None:
    _execute(
        """
        UPDATE tasks SET
            title = :title, video_id = :video_id, format = :format,
            status = :status, progress = :progress,
            downloaded_bytes = :downloaded_bytes, total_bytes = :total_bytes,
            speed = :speed, eta = :eta, item_index = :item_index,
            item_count = :item_count, completed_items = :completed_items,
            current_item_title = :current_item_title, playlist_id = :playlist_id,
            output_filename = :output_filename, error = :error,
            updated_at = :updated_at, completed_at = :completed_at
        WHERE task_id = :task_id
        """,
        task,
    )


def get_task(task_id: str) -> Optional[dict]:
    return _query_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))


def list_tasks(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict]:
    sql = "SELECT * FROM tasks"
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if search:
        clauses.append("(title LIKE ? OR url LIKE ? OR output_filename LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, task_id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return _query(sql, params)


def count_tasks(status: Optional[str] = None) -> int:
    if status:
        rows = _query("SELECT COUNT(*) AS n FROM tasks WHERE status = ?", (status,))
    else:
        rows = _query("SELECT COUNT(*) AS n FROM tasks")
    return rows[0]["n"] if rows else 0


# --------------------------------------------------------------------------- #
# Playlists
# --------------------------------------------------------------------------- #

def upsert_playlist(playlist: dict) -> None:
    existing = _query_one(
        "SELECT playlist_id FROM playlists WHERE playlist_id = ?",
        (playlist["playlist_id"],),
    )
    if existing:
        _execute(
            """
            UPDATE playlists SET
                url = :url, title = :title, channel = :channel,
                thumbnail_path = :thumbnail_path, item_count = :item_count,
                total_size = :total_size, zip_path = :zip_path, status = :status,
                updated_at = :updated_at
            WHERE playlist_id = :playlist_id
            """,
            playlist,
        )
    else:
        _execute(
            """
            INSERT INTO playlists (
                playlist_id, url, title, channel, thumbnail_path, item_count,
                total_size, zip_path, status, created_at, updated_at
            ) VALUES (
                :playlist_id, :url, :title, :channel, :thumbnail_path, :item_count,
                :total_size, :zip_path, :status, :created_at, :updated_at
            )
            """,
            playlist,
        )


def get_playlist(playlist_id: str) -> Optional[dict]:
    return _query_one("SELECT * FROM playlists WHERE playlist_id = ?", (playlist_id,))


def get_playlist_by_url(url: str) -> Optional[dict]:
    return _query_one("SELECT * FROM playlists WHERE url = ?", (url,))


def list_playlists() -> list[dict]:
    return _query("SELECT * FROM playlists ORDER BY updated_at DESC")


def delete_playlist(playlist_id: str) -> None:
    _execute("DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,))
    _execute("DELETE FROM playlists WHERE playlist_id = ?", (playlist_id,))


# --------------------------------------------------------------------------- #
# Playlist items
# --------------------------------------------------------------------------- #

def upsert_playlist_item(item: dict) -> None:
    _execute(
        """
        INSERT INTO playlist_items (
            playlist_id, item_index, video_id, url, title, duration,
            status, filename, size, error
        ) VALUES (
            :playlist_id, :item_index, :video_id, :url, :title, :duration,
            :status, :filename, :size, :error
        )
        ON CONFLICT(playlist_id, url) DO UPDATE SET
            title = excluded.title,
            duration = excluded.duration
        """,
        item,
    )


def update_playlist_item_status(playlist_id: str, url: str, status: str,
                                filename: str = "", size: int = 0,
                                error: str = "") -> None:
    _execute(
        """
        UPDATE playlist_items
        SET status = ?, filename = ?, size = ?, error = ?
        WHERE playlist_id = ? AND url = ?
        """,
        (status, filename, size, error, playlist_id, url),
    )


def get_playlist_items(playlist_id: str) -> list[dict]:
    return _query(
        "SELECT * FROM playlist_items WHERE playlist_id = ? ORDER BY item_index",
        (playlist_id,),
    )


def get_playlist_item(playlist_id: str, url: str) -> Optional[dict]:
    return _query_one(
        "SELECT * FROM playlist_items WHERE playlist_id = ? AND url = ?",
        (playlist_id, url),
    )


def find_item_by_filename(filename: str) -> str:
    """Return the playlist id owning a file, or an empty string."""
    row = _query_one(
        "SELECT playlist_id FROM playlist_items WHERE filename = ? LIMIT 1",
        (filename,),
    )
    return row["playlist_id"] if row else ""


def get_item_by_filename(filename: str) -> Optional[dict]:
    row = _query_one(
        "SELECT * FROM playlist_items WHERE filename = ? LIMIT 1", (filename,)
    )
    return row


def reset_downloading_items(playlist_id: str) -> None:
    """Reset in-flight items for a playlist back to pending."""
    _execute(
        "UPDATE playlist_items SET status = 'pending' WHERE playlist_id = ? AND status = 'downloading'",
        (playlist_id,),
    )


def prune_playlist_items(playlist_id: str, keep_urls: set[str]) -> int:
    """Delete tracked items whose URL is no longer in the source playlist.

    Returns the number of removed rows. Only the tracking rows are removed;
    media files on disk are intentionally left untouched (the storage policy is
    that nothing is deleted after packaging).
    """
    with _write_lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT url FROM playlist_items WHERE playlist_id = ?",
                (playlist_id,),
            ).fetchall()
            stale = [r["url"] for r in rows if r["url"] not in keep_urls]
            if stale:
                conn.executemany(
                    "DELETE FROM playlist_items WHERE playlist_id = ? AND url = ?",
                    [(playlist_id, url) for url in stale],
                )
                conn.commit()
            return len(stale)
        finally:
            conn.close()


def mark_interrupted_tasks() -> None:
    """Mark tasks left running by a previous process as interrupted."""
    now = iso_now()
    _execute(
        """
        UPDATE tasks SET status = 'failed',
            error = 'Interrupted by server restart.',
            completed_at = ?, updated_at = ?
        WHERE status IN (
            'queued', 'fetching information', 'downloading', 'processing'
        )
        """,
        (now, now),
    )
    _execute(
        "UPDATE playlist_items SET status = 'pending', error = '' WHERE status = 'downloading'"
    )


def find_file_owner(filename: str) -> Optional[dict]:
    """Return the (title, video_id) for a downloaded file, if known."""
    row = _query_one(
        "SELECT title, video_id FROM tasks WHERE output_filename = ? ORDER BY updated_at DESC LIMIT 1",
        (filename,),
    )
    if row:
        return {"title": row["title"], "video_id": row["video_id"]}
    row = _query_one(
        "SELECT title, video_id FROM playlist_items WHERE filename = ? LIMIT 1",
        (filename,),
    )
    if row:
        return {"title": row["title"], "video_id": row["video_id"]}
    return None
