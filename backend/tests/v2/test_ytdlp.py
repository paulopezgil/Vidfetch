"""Tests for the v2 yt-dlp service.

Every network surface is stubbed: DNS via ``socket.getaddrinfo``, yt-dlp via a
fake ``YoutubeDL`` class, and thumbnails via ``urllib.request.urlopen``.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pytest
import yt_dlp

from backend.app.services import ytdlp
from backend.tests.v2.fakes import make_settings

PUBLIC_IP = "93.184.216.34"


def _dns(ip: str = PUBLIC_IP):
    def resolve(host, port, *args, **kwargs):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port))]

    return resolve


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", _dns())
    return make_settings(tmp_path)


class FakeYDL:
    """Capture options and return canned metadata."""

    instances: list[dict] = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.instances.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=True):
        raise NotImplementedError


def _install_ydl(monkeypatch, factory):
    FakeYDL.instances = []

    class YDL(FakeYDL):
        def extract_info(self, url, download=True):
            return factory(self.opts, url, download)

    monkeypatch.setattr(ytdlp.yt_dlp, "YoutubeDL", YDL)
    return YDL


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.test/video",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "not a url",
        "https://",
        "https://user:pass@example.test/video",
        "https://@example.test/video",
    ],
)
def test_validate_media_url_rejects_bad_syntax(url, settings):
    with pytest.raises(ytdlp.DownloadError) as excinfo:
        ytdlp.validate_media_url(url, settings)

    assert excinfo.value.code == "invalid_url"


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.0.5",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "100.64.0.1",
        "::1",
        "fe80::1",
    ],
)
def test_validate_media_url_rejects_private_and_reserved_addresses(
    ip, tmp_path, monkeypatch
):
    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", _dns(ip))
    settings = make_settings(tmp_path)

    with pytest.raises(ytdlp.DownloadError) as excinfo:
        ytdlp.validate_media_url("https://media.example.test/v", settings)

    assert excinfo.value.code == "invalid_url"
    assert "private or reserved" in excinfo.value.message


def test_validate_media_url_accepts_public_addresses(settings):
    assert (
        ytdlp.validate_media_url("  https://media.example.test/v  ", settings)
        == "https://media.example.test/v"
    )


def test_validate_media_url_allows_private_only_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", _dns("127.0.0.1"))
    settings = make_settings(tmp_path, ALLOW_PRIVATE_URLS="true")

    assert (
        ytdlp.validate_media_url("http://localhost:8080/v", settings)
        == "http://localhost:8080/v"
    )


def test_validate_media_url_maps_dns_failure(tmp_path, monkeypatch):
    def failing(host, port, *args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", failing)
    settings = make_settings(tmp_path)

    with pytest.raises(ytdlp.DownloadError) as excinfo:
        ytdlp.validate_media_url("https://missing.example.test/v", settings)

    assert excinfo.value.code == "invalid_url"
    assert "resolve" in excinfo.value.message


# ---------------------------------------------------------------------------
# info extraction / normalization
# ---------------------------------------------------------------------------


def test_get_info_normalises_video_metadata(settings, monkeypatch):
    info = {
        "_type": "video",
        "id": "dQw4w9WgXcQ",
        "title": "A clip",
        "extractor_key": "Youtube",
        "duration": 212,
        "uploader": "Someone",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "thumbnail": "https://img.example.test/default.jpg",
        "thumbnails": [
            {"url": "https://img.example.test/small.jpg", "width": 120},
            {"url": "https://img.example.test/medium.jpg", "width": 320},
        ],
        "formats": [
            {"vcodec": "avc1", "height": 720, "acodec": "none"},
            {"vcodec": "none", "acodec": "opus"},
        ],
    }
    _install_ydl(monkeypatch, lambda opts, url, download: info)

    result = ytdlp.get_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", settings)

    assert result["type"] == "video"
    assert result["canonical_id"] == "youtube:dQw4w9WgXcQ"
    assert result["extractor_key"] == "youtube"
    assert result["title"] == "A clip"
    assert result["duration"] == 212
    assert result["thumbnail"] == "https://img.example.test/medium.jpg"
    assert result["formats"] == {
        "heights": [720],
        "has_720p": True,
        "has_audio": True,
    }

    opts = FakeYDL.instances[0]
    assert opts["skip_download"] is True
    assert opts["extract_flat"] == "in_playlist"
    assert opts["ignoreconfig"] is True
    assert opts["playlistend"] == settings.max_playlist_items
    assert opts["socket_timeout"] == 30


def test_get_info_truncates_and_annotates_playlist_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", _dns())
    settings = make_settings(tmp_path, MAX_PLAYLIST_ITEMS="2")
    info = {
        "_type": "playlist",
        "id": "PL123",
        "title": "My playlist",
        "extractor_key": "Youtube",
        "playlist_count": 3,
        "entries": [
            {
                "id": "one",
                "title": "One",
                "url": "https://example.test/one",
                "duration": 10,
            },
            {"id": "two", "title": "Two", "url": "https://example.test/two"},
            {"id": "three", "title": "Three", "url": "https://example.test/three"},
        ],
    }
    _install_ydl(monkeypatch, lambda opts, url, download: info)

    result = ytdlp.get_info("https://example.test/playlist", settings)

    assert result["type"] == "playlist"
    assert result["canonical_id"] == "youtube:PL123"
    assert result["item_count"] == 2
    assert result["truncated"] is True
    assert [entry["id"] for entry in result["entries"]] == ["one", "two"]
    assert result["entries"][0]["canonical_id"] == "youtube:one"
    assert result["entries"][1]["url"] == "https://example.test/two"
    assert FakeYDL.instances[0]["playlistend"] == 2


def test_get_info_maps_and_redacts_ytdlp_errors(settings, monkeypatch):
    _install_ydl(
        monkeypatch,
        lambda opts, url, download: (_ for _ in ()).throw(
            yt_dlp.utils.DownloadError(
                "HTTP Error 403: Forbidden https://user:secret@example.test/x?token=abc"
            )
        ),
    )

    with pytest.raises(ytdlp.DownloadError) as excinfo:
        ytdlp.get_info("https://example.test/v", settings)

    message = excinfo.value.message
    assert excinfo.value.code == "info_failed"
    assert "403" in message
    assert "user:secret" not in message
    assert "token=abc" not in message


# ---------------------------------------------------------------------------
# formats, intent, progress
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("mp3", "bestaudio/best"),
        ("720p", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"),
        ("best", "bestvideo+bestaudio/best"),
    ],
)
def test_format_spec_mapping(fmt, expected):
    assert ytdlp.format_spec(fmt) == expected
    assert ytdlp._format_spec(fmt) == expected


def test_format_spec_rejects_unknown_format():
    with pytest.raises(ytdlp.DownloadError) as excinfo:
        ytdlp.format_spec("4k")

    assert excinfo.value.code == "invalid_format"


def test_intent_encoding_round_trips():
    assert ytdlp.encode_intent("720p", True) == "720p+subs"
    assert ytdlp.parse_intent("720p+subs") == ("720p", True)
    assert ytdlp.parse_intent("mp3") == ("mp3", False)
    assert ytdlp.parse_intent("nonsense") == ("best", False)


def _download_factory(progress: bool = False, cancelled: bool = False):
    def factory(opts, url, download):
        if progress:
            hook = opts["progress_hooks"][0]
            hook(
                {
                    "status": "downloading",
                    "downloaded_bytes": 512,
                    "total_bytes": 1024,
                    "speed": 2048.0,
                    "eta": 7,
                }
            )
            hook(
                {
                    "status": "finished",
                    "downloaded_bytes": 1024,
                    "total_bytes": 1024,
                }
            )
        path = Path(
            opts["outtmpl"].replace("%(id)s", "vid1").replace("%(ext)s", "mp4")
        )
        path.write_bytes(b"media-bytes")
        return {
            "id": "vid1",
            "title": "Clip",
            "ext": "mp4",
            "extractor_key": "Youtube",
            "thumbnail": "https://img.example.test/t.jpg",
            "requested_downloads": [{"filepath": str(path)}],
        }

    return factory


def test_download_video_reports_progress_and_returns_result(
    tmp_path, settings, monkeypatch
):
    _install_ydl(monkeypatch, _download_factory(progress=True))
    workdir = tmp_path / "work"
    seen: list[dict] = []

    result = ytdlp.download_video(
        "https://example.test/v",
        "720p",
        False,
        workdir,
        seen.append,
        lambda: False,
        settings,
    )

    assert result["id"] == "vid1"
    assert result["canonical_id"] == "youtube:vid1"
    assert result["filepath"] == str(workdir / "vid1.mp4")
    assert result["ext"] == "mp4"
    assert Path(result["filepath"]).read_bytes() == b"media-bytes"

    downloading, finished = seen
    assert downloading["status"] == "downloading"
    assert downloading["downloaded_bytes"] == 512
    assert downloading["total_bytes"] == 1024
    assert downloading["speed"] == 2048.0
    assert downloading["eta"] == 7
    assert downloading["percent"] == 50.0
    assert finished["status"] == "processing"
    assert finished["percent"] == 100.0

    opts = FakeYDL.instances[0]
    assert opts["noplaylist"] is True
    assert opts["ignoreconfig"] is True
    assert opts["max_filesize"] == settings.max_asset_bytes
    assert opts["socket_timeout"] == 30
    assert opts["format"] == ytdlp.format_spec("720p")
    assert opts["merge_output_format"] == "mp4"


def test_download_video_mp3_uses_audio_extraction(tmp_path, settings, monkeypatch):
    _install_ydl(monkeypatch, _download_factory())

    ytdlp.download_video(
        "https://example.test/v",
        "mp3",
        False,
        tmp_path / "work",
        lambda payload: None,
        lambda: False,
        settings,
        album="My album",
    )

    opts = FakeYDL.instances[0]
    assert opts["format"] == "bestaudio/best"
    assert opts["postprocessors"][0]["key"] == "FFmpegExtractAudio"
    assert opts["postprocessors"][0]["preferredquality"] == "192"
    assert opts["postprocessor_args"] == {
        "ffmpeg": ["-metadata", "album=My album"]
    }
    assert "merge_output_format" not in opts


def test_download_video_embeds_subtitles(tmp_path, settings, monkeypatch):
    _install_ydl(monkeypatch, _download_factory())

    ytdlp.download_video(
        "https://example.test/v",
        "best",
        True,
        tmp_path / "work",
        lambda payload: None,
        lambda: False,
        settings,
    )

    opts = FakeYDL.instances[0]
    assert opts["writesubtitles"] is True
    assert opts["embedsubtitles"] is True
    assert opts["subtitleslangs"] == ["en"]
    assert opts["postprocessors"][0]["key"] == "FFmpegEmbedSubtitle"


def test_download_video_progress_hook_aborts_on_cancel(tmp_path, settings, monkeypatch):
    _install_ydl(monkeypatch, _download_factory(progress=True))

    with pytest.raises(ytdlp.DownloadCancelled):
        ytdlp.download_video(
            "https://example.test/v",
            "best",
            False,
            tmp_path / "work",
            lambda payload: None,
            lambda: True,
            settings,
        )


def test_download_video_maps_failures_and_redacts(tmp_path, settings, monkeypatch):
    _install_ydl(
        monkeypatch,
        lambda opts, url, download: (_ for _ in ()).throw(
            yt_dlp.utils.DownloadError(
                "connection refused for https://user:pass@example.test/v?api_key=xyz"
            )
        ),
    )

    with pytest.raises(ytdlp.DownloadError) as excinfo:
        ytdlp.download_video(
            "https://example.test/v",
            "best",
            False,
            tmp_path / "work",
            lambda payload: None,
            lambda: False,
            settings,
        )

    assert excinfo.value.code == "download_failed"
    assert "Network error" in excinfo.value.message
    assert "user:pass" not in excinfo.value.message


def test_download_video_without_output_file_fails(tmp_path, settings, monkeypatch):
    _install_ydl(
        monkeypatch,
        lambda opts, url, download: {
            "id": "vid1",
            "title": "Clip",
            "requested_downloads": [],
        },
    )

    with pytest.raises(ytdlp.DownloadError) as excinfo:
        ytdlp.download_video(
            "https://example.test/v",
            "best",
            False,
            tmp_path / "work",
            lambda payload: None,
            lambda: False,
            settings,
        )

    assert "no file" in excinfo.value.message


# ---------------------------------------------------------------------------
# thumbnails
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, amount=None):
        return self._data if amount is None else self._data[:amount]


def test_download_thumbnail_writes_file(tmp_path, settings, monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["ua"] = request.get_header("User-agent")
        return _Response(b"jpeg-bytes")

    monkeypatch.setattr(ytdlp.urllib.request, "urlopen", fake_urlopen)
    dest = tmp_path / "thumbs" / "asset.jpg"

    assert (
        ytdlp.download_thumbnail("https://img.example.test/t.jpg", dest, settings)
        is True
    )

    assert dest.read_bytes() == b"jpeg-bytes"
    assert not dest.with_name(dest.name + ".part").exists()
    assert captured["url"] == "https://img.example.test/t.jpg"
    assert captured["timeout"] == ytdlp.THUMBNAIL_TIMEOUT_SECONDS
    assert "Mozilla" in captured["ua"]


def test_download_thumbnail_failure_cleans_partial_file(
    tmp_path, settings, monkeypatch
):
    def failing(request, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(ytdlp.urllib.request, "urlopen", failing)
    dest = tmp_path / "thumbs" / "asset.jpg"
    dest.parent.mkdir(parents=True)
    partial = dest.with_name(dest.name + ".part")
    partial.write_bytes(b"half")

    assert (
        ytdlp.download_thumbnail("https://img.example.test/t.jpg", dest, settings)
        is False
    )

    assert not dest.exists()
    assert not partial.exists()


def test_download_thumbnail_rejects_oversized_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", _dns())
    settings = make_settings(tmp_path, MAX_ASSET_BYTES="4")

    monkeypatch.setattr(
        ytdlp.urllib.request,
        "urlopen",
        lambda request, timeout=None: _Response(b"12345"),
    )
    dest = tmp_path / "thumbs" / "asset.jpg"

    assert (
        ytdlp.download_thumbnail("https://img.example.test/t.jpg", dest, settings)
        is False
    )
    assert not dest.exists()


# ---------------------------------------------------------------------------
# redaction / friendly errors
# ---------------------------------------------------------------------------


def test_redact_sensitive_strips_userinfo_headers_and_query_secrets():
    raw = (
        "GET https://alice:hunter2@example.test/v?access_token=secret&x=1 "
        "Authorization: Bearer abc Cookie: sid=123"
    )

    redacted = ytdlp.redact_sensitive(raw)

    assert "hunter2" not in redacted
    assert "access_token=secret" not in redacted
    assert "Bearer abc" not in redacted
    assert "sid=123" not in redacted
    assert "example.test" in redacted


def test_friendly_error_network_and_unsupported():
    assert "Network error" in ytdlp.friendly_error(
        RuntimeError("getaddrinfo failed")
    )
    assert "Unsupported" in ytdlp.friendly_error(
        RuntimeError("Unsupported URL: foo")
    )


def test_embed_cover_art_is_best_effort_without_files(tmp_path):
    assert ytdlp._embed_cover_art(tmp_path / "missing.mp3", tmp_path / "c.jpg") is False
