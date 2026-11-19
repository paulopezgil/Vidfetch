"""Schema migration tests for the SQLite store.

These exercise real databases on disk: a legacy ``playlists`` table is created
by hand (without the ``format`` column) and then ``init_db()`` is run against
it, exactly as it would be on an existing installation after an upgrade.
"""
import sqlite3

import pytest

from backend import database
from backend.config import settings


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "download_dir", downloads.resolve())
    monkeypatch.setattr(settings, "thumb_dir", (downloads / ".thumbnails").resolve())
    monkeypatch.setattr(settings, "tmp_dir", (downloads / ".tmp").resolve())
    monkeypatch.setattr(settings, "data_dir", data.resolve())
    monkeypatch.setattr(settings, "db_path", (data / "test.db").resolve())
    data.mkdir(parents=True, exist_ok=True)
    return settings.db_path


def _create_legacy_playlists_table(path) -> None:
    """Recreate the pre-``format`` schema and seed one row."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE playlists (
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
            )
            """
        )
        conn.execute(
            """
            INSERT INTO playlists (
                playlist_id, url, title, channel, thumbnail_path, item_count,
                total_size, zip_path, status, created_at, updated_at
            ) VALUES (
                'pl_legacy', 'https://example.com/list', 'Old List', '', '',
                3, 0, '', 'completed', '2024-01-01T00:00:00Z',
                '2024-01-01T00:00:00Z'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_init_db_adds_format_to_legacy_playlists(db_path):
    _create_legacy_playlists_table(db_path)

    database.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(playlists)").fetchall()
        }
    finally:
        conn.close()
    assert "format" in columns

    row = database.get_playlist("pl_legacy")
    assert row is not None
    # Existing rows are backfilled by the column default.
    assert row["format"] == "best"
    # The rest of the legacy row is preserved intact.
    assert row["title"] == "Old List"
    assert row["item_count"] == 3


def test_init_db_is_idempotent_after_format_migration(db_path):
    _create_legacy_playlists_table(db_path)

    database.init_db()
    database.init_db()

    conn = sqlite3.connect(str(db_path))
    try:
        columns = [
            row[1] for row in conn.execute("PRAGMA table_info(playlists)").fetchall()
        ]
    finally:
        conn.close()
    # The ALTER TABLE must only run once; a duplicate column would fail.
    assert columns.count("format") == 1
    assert database.get_playlist("pl_legacy")["format"] == "best"


def test_upsert_playlist_updates_stored_format(db_path):
    database.init_db()
    now = database.iso_now()
    base = {
        "playlist_id": "pl_x",
        "url": "https://example.com/list",
        "title": "List",
        "channel": "",
        "thumbnail_path": "",
        "item_count": 1,
        "total_size": 0,
        "zip_path": "",
        "status": "completed",
        "created_at": now,
        "updated_at": now,
    }

    database.upsert_playlist({**base, "format": "mp3"})
    assert database.get_playlist("pl_x")["format"] == "mp3"

    # The UPDATE branch must overwrite the previously stored value.
    database.upsert_playlist({**base, "format": "720p"})
    assert database.get_playlist("pl_x")["format"] == "720p"
