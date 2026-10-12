"""HTTP endpoint tests using FastAPI's TestClient.

Settings are redirected at a tmp directory so nothing touches the real data
dir, and the yt-dlp service is stubbed wherever a download task would otherwise
hit the network.
"""
import time
import uuid

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
