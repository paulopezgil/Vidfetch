"""HTTP endpoint tests using FastAPI's TestClient.

Settings are redirected at a tmp directory so nothing touches the real data
dir, and the yt-dlp service is stubbed wherever a download task would otherwise
hit the network.
"""
import io
import time
import uuid
import zipfile
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.config import settings
from backend.main import app
from backend.services import ytdlp_service
from backend.services.task_manager import Task


@pytest.fixture
def env(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "download_dir", downloads.resolve())
    monkeypatch.setattr(settings, "thumb_dir", (downloads / ".thumbnails").resolve())
    monkeypatch.setattr(settings, "tmp_dir", (downloads / ".tmp").resolve())
    monkeypatch.setattr(settings, "data_dir", data.resolve())
    monkeypatch.setattr(settings, "db_path", (data / "test.db").resolve())
    database.init_db()
    return downloads


@pytest.fixture
def client(env):
    with TestClient(app) as c:
        yield c


def _seed_task(status: str) -> str:
    task = Task(
        task_id=uuid.uuid4().hex,
        url=f"https://example.com/{status}/{uuid.uuid4().hex[:6]}",
        operation_type="video",
        status=status,
    )
    database.insert_task(task._row())
    return task.task_id


def _seed_playlist(playlist_id: str, title: str = "My List", items=()) -> None:
    now = database.iso_now()
    database.upsert_playlist({
        "playlist_id": playlist_id,
        "url": f"https://example.com/{playlist_id}",
        "title": title,
        "channel": "",
        "thumbnail_path": "",
        "item_count": len(items),
        "total_size": 0,
        "zip_path": "",
        "status": "completed",
        "created_at": now,
        "updated_at": now,
    })
    for item in items:
        database.upsert_playlist_item({
            "playlist_id": playlist_id,
            "duration": 1,
            "error": "",
            **item,
        })


def _item(index, vid, status, filename="", size=0):
    return {
        "item_index": index,
        "video_id": vid,
        "url": f"https://example.com/{vid}",
        "title": vid.upper(),
        "status": status,
        "filename": filename,
        "size": size,
    }


def _wait_terminal(client, task_id, timeout=10.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/tasks/{task_id}").json()["status"]
        if status in ("completed", "failed", "cancelled"):
            return status
        time.sleep(0.05)
    return "timeout"


# -- info ----------------------------------------------------------------- #

def test_info_invalid_url_returns_422(client):
    assert client.post("/api/info", json={"url": "not-a-url"}).status_code == 422
    assert client.post("/api/info", json={"url": ""}).status_code == 422


# -- download ------------------------------------------------------------- #

@pytest.mark.parametrize("payload", [
    {"url": "https://example.com/v", "format": "8k"},
    {"url": "https://example.com/v", "operation_type": "album"},
    {"url": "not-a-url"},
])
def test_download_invalid_payload_returns_422(client, payload):
    assert client.post("/api/download", json=payload).status_code == 422


def test_download_valid_returns_202_and_task_id(client, monkeypatch):
    # Fail metadata instantly so the scheduled task never touches the network.
    def boom(url):
        raise ytdlp_service.DownloadError("stub: no network in tests")

    monkeypatch.setattr(ytdlp_service, "get_info", boom)

    r = client.post("/api/download", json={
        "url": "https://example.com/v", "operation_type": "video", "format": "720p",
    })
    assert r.status_code == 202
    task_id = r.json()["task_id"]
    assert isinstance(task_id, str) and task_id
    # The task is registered and reaches a terminal state without network.
    assert _wait_terminal(client, task_id) == "failed"


# -- library -------------------------------------------------------------- #

def test_downloads_response_shape(client, env):
    (env / "video.mp4").write_bytes(b"data")
    (env / ".hidden").write_bytes(b"secret")

    r = client.get("/api/downloads")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"files", "playlists"}

    names = [f["filename"] for f in body["files"]]
    assert "video.mp4" in names
    assert ".hidden" not in names

    entry = next(f for f in body["files"] if f["filename"] == "video.mp4")
    assert {
        "filename", "title", "size", "mtime", "ext", "media_type", "thumbnail_url",
    } <= set(entry)


# -- history -------------------------------------------------------------- #

def test_history_pagination_and_status_filter(client):
    for status in ("completed", "failed", "completed"):
        _seed_task(status)

    everything = client.get("/api/history").json()
    assert everything["total"] == 3

    page1 = client.get("/api/history", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/api/history", params={"limit": 2, "offset": 2}).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    ids1 = {i["task_id"] for i in page1["items"]}
    ids2 = {i["task_id"] for i in page2["items"]}
    assert ids1.isdisjoint(ids2)

    failed = client.get("/api/history", params={"status": "failed"}).json()
    assert failed["total"] == 1
    assert failed["items"][0]["status"] == "failed"

    # An unknown status is ignored rather than returning nothing.
    bogus = client.get("/api/history", params={"status": "bogus"}).json()
    assert bogus["total"] == 3


# -- files ---------------------------------------------------------------- #

def test_file_download_valid(client, env):
    (env / "video.mp4").write_bytes(b"data")
    r = client.get("/api/file/video.mp4")
    assert r.status_code == 200
    assert r.content == b"data"


def test_file_path_traversal_blocked(client):
    # Encoded separators must be decoded into the path param and rejected.
    assert client.get("/api/file/%2e%2e%2f%2e%2e%2fetc%2fpasswd").status_code == 404
    # A literally-spliced path must not resolve to anything either.
    assert client.get("/api/file/../../etc/passwd").status_code == 404
    assert client.get("/api/file/missing.mp4").status_code == 404


# -- tasks / health ------------------------------------------------------- #

def test_cancel_unknown_task_returns_409(client):
    assert client.post("/api/tasks/does-not-exist/cancel").status_code == 409


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert {"node_available", "ffmpeg_available"} <= set(body["dependencies"])


# -- playlist ZIP (on demand) --------------------------------------------- #

def test_playlist_zip_unknown_returns_404(client):
    assert client.get("/api/playlists/nope/zip").status_code == 404


def test_playlist_zip_without_downloaded_files_returns_409(client, env):
    _seed_playlist("pl_empty", items=[_item(0, "a", "failed")])
    r = client.get("/api/playlists/pl_empty/zip")
    assert r.status_code == 409
    assert r.json()["detail"]


def test_playlist_zip_includes_redownloaded_item_and_is_transient(client, env):
    (env / "a.mp4").write_bytes(b"aaaa")
    _seed_playlist("pl_zip", title="My List", items=[
        _item(0, "a", "downloaded", "a.mp4", 4),
        _item(1, "b", "failed"),
    ])

    # Before the retry only the successful item is packaged.
    first = client.get("/api/playlists/pl_zip/zip")
    assert first.status_code == 200
    assert first.headers["content-type"] == "application/zip"
    assert first.headers["content-disposition"].startswith("attachment")
    assert "My List [pl_zip].zip" in unquote(first.headers["content-disposition"])
    assert zipfile.ZipFile(io.BytesIO(first.content)).namelist() == ["a.mp4"]

    # The failed item is retried: its file lands on disk and the row is updated.
    (env / "b.mp4").write_bytes(b"bbbb")
    database.update_playlist_item_status(
        "pl_zip", "https://example.com/b", "downloaded", "b.mp4", 4, ""
    )

    second = client.get("/api/playlists/pl_zip/zip")
    assert second.status_code == 200
    assert set(zipfile.ZipFile(io.BytesIO(second.content)).namelist()) == {
        "a.mp4", "b.mp4",
    }

    # Nothing is persisted: no archive anywhere, and the transient temp file
    # has been removed after the response was sent.
    assert not list(env.rglob("*.zip"))
    leftovers = [p for p in (env / ".tmp").rglob("*") if p.is_file()]
    assert leftovers == []
    on_disk = sorted(p.name for p in env.iterdir() if p.is_file())
    assert on_disk == ["a.mp4", "b.mp4"]


# -- downloaded_count ----------------------------------------------------- #

def test_downloaded_count_in_library_and_playlist_detail(client, env):
    (env / "a.mp4").write_bytes(b"aaaa")
    _seed_playlist("pl_count", title="Counted", items=[
        _item(0, "a", "downloaded", "a.mp4", 4),
        _item(1, "b", "downloaded", "gone.mp4", 4),  # file missing on disk
        _item(2, "c", "failed"),
    ])

    listing = client.get("/api/downloads").json()
    pl = next(p for p in listing["playlists"] if p["playlist_id"] == "pl_count")
    assert pl["downloaded_count"] == 1
    assert "zip_path" not in pl

    detail = client.get("/api/playlists/pl_count").json()
    assert detail["downloaded_count"] == 1
    assert "zip_path" not in detail


# -- inline media --------------------------------------------------------- #

def test_media_served_inline_and_file_stays_attachment(client, env):
    (env / "clip.mp4").write_bytes(b"0123456789")

    inline = client.get("/api/media/clip.mp4")
    assert inline.status_code == 200
    assert inline.headers["content-type"] == "video/mp4"
    assert inline.headers["content-disposition"].startswith("inline")
    assert inline.content == b"0123456789"

    attached = client.get("/api/file/clip.mp4")
    assert attached.status_code == 200
    assert attached.headers["content-disposition"].startswith("attachment")
    assert attached.content == b"0123456789"


def test_media_image_content_type(client, env):
    (env / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    r = client.get("/api/media/pic.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_media_range_request_returns_206(client, env):
    (env / "clip.mp4").write_bytes(b"0123456789")
    r = client.get("/api/media/clip.mp4", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 0-3/10"
    assert r.content == b"0123"


def test_media_rejects_traversal_and_unknown(client):
    assert client.get("/api/media/%2e%2e%2f%2e%2e%2fetc%2fpasswd").status_code == 404
    assert client.get("/api/media/../../etc/passwd").status_code == 404
    assert client.get("/api/media/missing.mp4").status_code == 404
