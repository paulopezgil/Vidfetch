"""Tests for the thin yt-dlp service layer.

These cover the pure helpers (error translation, format/thumbnail selection,
progress mapping) and the cancellation short-circuit without touching the
network.
"""
import pytest

from backend.services import ytdlp_service


# -- friendly_error ------------------------------------------------------- #

def test_friendly_error_detects_403():
    msg = ytdlp_service.friendly_error(
        Exception("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    )
    assert "403" in msg
    assert "troubleshooting" in msg.lower()


def test_friendly_error_detects_429():
    msg = ytdlp_service.friendly_error(Exception("HTTP Error 429: Too Many Requests"))
    assert "429" in msg


def test_friendly_error_does_not_false_positive_on_larger_numbers():
    # "4032" must not be read as a 403.
    msg = ytdlp_service.friendly_error(Exception("downloaded 4032 bytes"))
    assert "HTTP 403" not in msg
    assert msg == "downloaded 4032 bytes"


def test_friendly_error_does_not_false_positive_on_age_substring():
    # "language" contains "age"; it must not be reported as age-restricted.
    msg = ytdlp_service.friendly_error(
        Exception("Requested subtitle language en is not available")
    )
    assert "sign-in" not in msg.lower()
    assert "language" in msg


def test_friendly_error_detects_age_restriction():
    msg = ytdlp_service.friendly_error(
        Exception("Sign in to confirm your age. This video may be inappropriate")
    )
    assert "age confirmation" in msg.lower()


def test_friendly_error_detects_ffmpeg_and_unsupported():
    assert "FFmpeg" in ytdlp_service.friendly_error(
        Exception("ffprobe not found")
    )
    assert "Unsupported" in ytdlp_service.friendly_error(
        Exception("Unsupported URL: example.com")
    )


def test_friendly_error_truncates_long_messages():
    msg = ytdlp_service.friendly_error(Exception("x" * 2000))
    assert len(msg) <= 500


# -- helpers -------------------------------------------------------------- #

@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("mp3", "bestaudio/best"),
        ("720p", "bestvideo[height<=720]+bestaudio/best[height<=720]/best"),
        ("best", "bestvideo+bestaudio/best"),
    ],
)
def test_format_spec(fmt, expected):
    assert ytdlp_service._format_spec(fmt) == expected


def test_percent_uses_estimate_and_clamps():
    assert ytdlp_service._percent(
        {"downloaded_bytes": 50, "total_bytes_estimate": 100}
    ) == 50.0
    # Over-reported progress is clamped to 100.
    assert ytdlp_service._percent(
        {"downloaded_bytes": 200, "total_bytes": 100}
    ) == 100.0
    # Unknown total reports 0 rather than dividing by zero.
    assert ytdlp_service._percent({"downloaded_bytes": 10}) == 0.0


def test_summarise_formats():
    summary = ytdlp_service._summarise_formats([
        {"vcodec": "avc1", "height": 1080, "acodec": "none"},
        {"vcodec": "avc1", "height": 720, "acodec": "none"},
        {"vcodec": "none", "acodec": "mp4a"},
    ])
    assert summary["heights"] == [1080, 720]
    assert summary["has_720p"] is True
    assert summary["has_audio"] is True


def test_pick_thumbnail_prefers_medium_width():
    info = {
        "thumbnail": "fallback",
        "thumbnails": [
            {"url": "tiny", "width": 64},
            {"url": "medium", "width": 320},
            {"url": "huge", "width": 1920},
        ],
    }
    assert ytdlp_service._pick_thumbnail(info) == "medium"
    # No medium match falls back to the last (largest) thumbnail.
    assert ytdlp_service._pick_thumbnail(
        {"thumbnails": [{"url": "tiny", "width": 64}, {"url": "huge", "width": 1920}]}
    ) == "huge"


def test_normalise_info_playlist_filters_entries_without_url():
    info = {
        "_type": "playlist",
        "id": "PL1",
        "title": "My Playlist",
        "uploader": "Someone",
        "playlist_count": 2,
        "entries": [
            {"id": "a", "title": "A", "url": "https://e/a"},
            {"id": "b", "title": "B"},  # no url -> dropped
            None,
        ],
    }
    out = ytdlp_service._normalise_info(info)
    assert out["type"] == "playlist"
    assert out["channel"] == "Someone"
    assert [e["id"] for e in out["entries"]] == ["a"]


def test_normalise_info_video():
    out = ytdlp_service._normalise_info({
        "id": "v1",
        "title": "Video",
        "formats": [{"vcodec": "avc1", "height": 720, "acodec": "mp4a"}],
    })
    assert out["type"] == "video"
    assert out["formats"]["has_720p"] is True


# -- progress hook / cancellation ---------------------------------------- #

def test_progress_hook_maps_downloading_and_finished():
    seen: list[dict] = []
    hook = ytdlp_service._make_progress_hook(seen.append, lambda: False)
    hook({
        "status": "downloading",
        "downloaded_bytes": 50,
        "total_bytes": 100,
        "speed": 1234.0,
        "eta": 5.0,
    })
    assert seen[0] == {
        "status": "downloading",
        "downloaded_bytes": 50,
        "total_bytes": 100,
        "speed": 1234.0,
        "eta": 5.0,
        "percent": 50.0,
    }
    hook({"status": "finished"})
    assert seen[-1] == {"status": "processing"}


def test_progress_hook_raises_when_cancelled():
    hook = ytdlp_service._make_progress_hook(lambda d: None, lambda: True)
    with pytest.raises(ytdlp_service.DownloadCancelled):
        hook({"status": "downloading"})


def test_download_video_short_circuits_when_already_cancelled(tmp_path):
    # Must not open a yt-dlp session / touch the network.
    with pytest.raises(ytdlp_service.DownloadCancelled):
        ytdlp_service.download_video(
            "https://example.com/video",
            "best",
            False,
            tmp_path,
            lambda d: None,
            lambda: True,
        )


# -- robustness: disk space, ffmpeg, network, secrets --------------------- #

class _FakeUsage:
    def __init__(self, free: int):
        self.free = free
        self.total = free
        self.used = 0


def test_free_space_check_rejects_low_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(ytdlp_service.shutil, "disk_usage", lambda path: _FakeUsage(1))
    with pytest.raises(ytdlp_service.DownloadError) as exc:
        ytdlp_service._check_free_space(tmp_path)
    assert "disk space" in str(exc.value).lower()


def test_free_space_check_allows_plenty(monkeypatch, tmp_path):
    huge = ytdlp_service.settings.min_free_disk_mb * 1024 * 1024 + 1
    monkeypatch.setattr(
        ytdlp_service.shutil, "disk_usage", lambda path: _FakeUsage(huge)
    )
    ytdlp_service._check_free_space(tmp_path)  # must not raise


def test_download_video_rejects_when_disk_full(monkeypatch, tmp_path):
    monkeypatch.setattr(ytdlp_service.shutil, "disk_usage", lambda path: _FakeUsage(1))
    with pytest.raises(ytdlp_service.DownloadError) as exc:
        ytdlp_service.download_video(
            "https://example.com/video", "best", False, tmp_path,
            lambda d: None, lambda: False,
        )
    assert "disk space" in str(exc.value).lower()


def test_friendly_error_maps_ffmpeg_missing():
    msg = ytdlp_service.friendly_error(
        Exception("ERROR: Postprocessing: ffmpeg not found. Please install or provide")
    )
    assert "FFmpeg" in msg


def test_friendly_error_maps_network_failures():
    for raw in (
        "ERROR: Unable to download webpage: <urlopen error [Errno -3] Temporary failure in name resolution>",
        "ERROR: [Errno 111] Connection refused",
        "ERROR: The read operation timed out",
    ):
        assert "Network error" in ytdlp_service.friendly_error(Exception(raw))


def test_friendly_error_maps_enospc():
    msg = ytdlp_service.friendly_error(
        Exception("ERROR: unable to write data: [Errno 28] No space left on device")
    )
    assert "disk space" in msg.lower()


def test_redact_sensitive_strips_credentials():
    raw = (
        "GET https://user:s3cret@example.com/x?token=abc123&sig=deadbeef HTTP/1.1\n"
        "Cookie: SID=verysecretvalue\n"
        "Authorization: Bearer xyz"
    )
    out = ytdlp_service.redact_sensitive(raw)
    assert "s3cret" not in out
    assert "user@" not in out
    assert "abc123" not in out
    assert "deadbeef" not in out
    assert "verysecretvalue" not in out
    assert "Bearer xyz" not in out
    # ...but harmless structure is retained.
    assert "https://example.com/x" in out


def test_friendly_error_redacts_secrets_in_fallback():
    msg = ytdlp_service.friendly_error(
        Exception("bad request to https://u:p@example.com/v?token=leak")
    )
    assert "leak" not in msg
    assert "u:p@" not in msg


def test_base_opts_never_carry_credentials():
    opts = ytdlp_service._base_opts()
    for key in ("cookiefile", "cookiesfrombrowser", "username", "password",
                "videopassword", "http_headers"):
        assert key not in opts
