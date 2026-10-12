"""Thin service layer around ``yt-dlp``.

All media downloading and metadata extraction goes through this module so the
rest of the application never touches ``yt_dlp`` directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from ..config import settings


class DownloadError(Exception):
    """A download or metadata operation failed for a known reason."""


class DownloadCancelled(Exception):
    """The download was cancelled by the user."""


ProgressCallback = Callable[[dict], None]
CancelCheck = Callable[[], bool]


def _base_opts() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "noplaylist": False,
        # Keep Unicode titles; we sanitise paths ourselves.
        "restrictfilenames": False,
        "windowsfilenames": False,
        # Never touch anything outside our own directories.
        "outtmpl": str(settings.tmp_dir / "%(id)s.%(ext)s"),
    }


def _pick_thumbnail(info: dict) -> Optional[str]:
    thumbs = info.get("thumbnails") or []
    if not thumbs:
        return info.get("thumbnail")
    # Prefer a medium-sized thumbnail; fall back to the last (largest).
    for t in thumbs:
        if t and 160 <= (t.get("width") or 0) <= 480:
            return t.get("url")
    return thumbs[-1].get("url") if thumbs[-1] else info.get("thumbnail")


def _percent(d: dict) -> float:
    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
    downloaded = d.get("downloaded_bytes") or 0
    if total and total > 0:
        return round(min(downloaded / total, 1.0) * 100, 1)
    return 0.0


def _make_progress_hook(callback: ProgressCallback, cancel: CancelCheck):
    def hook(d: dict) -> None:
        if cancel and cancel():
            raise DownloadCancelled()
        status = d.get("status")
        if status == "downloading":
            callback({
                "status": "downloading",
                "downloaded_bytes": d.get("downloaded_bytes") or 0,
                "total_bytes": d.get("total_bytes")
                or d.get("total_bytes_estimate") or 0,
                "speed": d.get("speed") or 0.0,
                "eta": d.get("eta") or 0.0,
                "percent": _percent(d),
            })
        elif status == "finished":
            callback({"status": "processing"})

    return hook


def get_info(url: str) -> dict:
    """Return normalised metadata for a single video or a playlist.

    ``extract_flat="in_playlist"`` returns playlist entries without fetching
    each video's full metadata, so previews stay fast for large playlists.
    No media is downloaded here.
    """
    opts = _base_opts()
    opts.update({"skip_download": True, "extract_flat": "in_playlist"})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(friendly_error(exc)) from exc
    if info is None:
        raise DownloadError("Could not retrieve information for this URL.")
    return _normalise_info(info)


def _normalise_info(info: dict) -> dict:
    if info.get("_type") == "playlist" or (
        "entries" in info and info.get("playlist_count") is not None
    ):
        entries = [e for e in (info.get("entries") or []) if e]
        return {
            "type": "playlist",
            "id": info.get("id") or info.get("playlist_id"),
            "title": info.get("title") or "Untitled playlist",
            "channel": info.get("uploader") or info.get("channel"),
            "thumbnail": _pick_thumbnail(info),
            "video_count": info.get("playlist_count") or len(entries),
            "entries": [
                {
                    "id": e.get("id"),
                    "title": e.get("title"),
                    "url": e.get("url") or e.get("webpage_url"),
                    "duration": e.get("duration"),
                    "thumbnail": _pick_thumbnail(e),
                }
                for e in entries
                if e.get("url") or e.get("webpage_url")
            ],
        }

    return {
        "type": "video",
        "id": info.get("id"),
        "title": info.get("title") or "Untitled video",
        "channel": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": _pick_thumbnail(info),
        "formats": _summarise_formats(info.get("formats")),
        "ext": info.get("ext"),
        "webpage_url": info.get("webpage_url") or info.get("original_url"),
    }


def _summarise_formats(formats: list | None) -> dict:
    """Return a compact description of what quality/audio options exist."""
    heights: set[int] = set()
    has_audio = False
    for f in formats or []:
        if f.get("vcodec") not in (None, "none"):
            if f.get("height"):
                heights.add(int(f["height"]))
        if f.get("acodec") not in (None, "none"):
            has_audio = True
    return {
        "heights": sorted(heights, reverse=True),
        "has_720p": any(h >= 720 for h in heights),
        "has_audio": has_audio,
    }


def _format_spec(fmt: str) -> str:
    if fmt == "mp3":
        return "bestaudio/best"
    if fmt == "720p":
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    return "bestvideo+bestaudio/best"


def download_video(
    url: str,
    fmt: str,
    embed_subs: bool,
    workdir: Path,
    progress_cb: ProgressCallback,
    cancel: CancelCheck,
) -> dict:
    """Download a single video into ``workdir`` and return its result info.

    Returns a dict with ``id``, ``title``, ``filepath``, ``thumbnail``, ``ext``.
    """
    opts = _base_opts()
    opts["outtmpl"] = str(workdir / "%(id)s.%(ext)s")
    opts["format"] = _format_spec(fmt)
    opts["progress_hooks"] = [_make_progress_hook(progress_cb, cancel)]

    postprocessors: list[dict] = []

    if fmt == "mp3":
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        })
    else:
        opts["merge_output_format"] = "mp4"

    if embed_subs:
        opts.update({
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "embedsubtitles": True,
        })
        postprocessors.append({
            "key": "FFmpegEmbedSubtitle",
            "already_have_subtitle": False,
        })

    if postprocessors:
        opts["postprocessors"] = postprocessors

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadCancelled:
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(friendly_error(exc)) from exc

    if info is None:
        raise DownloadError("Download produced no result.")

    filepath = _result_filepath(info)
    return {
        "id": info.get("id"),
        "title": info.get("title") or "download",
        "filepath": filepath,
        "thumbnail": _pick_thumbnail(info),
        "ext": Path(filepath).suffix.lstrip(".") if filepath else None,
    }


def _result_filepath(info: dict) -> Optional[str]:
    requested = info.get("requested_downloads") or []
    for item in requested:
        if item.get("filepath"):
            return item["filepath"]
    return info.get("_filename") or info.get("filepath")


def get_playlist_entries(url: str) -> list[dict]:
    """Return the flat list of entries for a playlist URL."""
    opts = _base_opts()
    opts.update({"skip_download": True, "extract_flat": "in_playlist"})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(friendly_error(exc)) from exc
    if info is None or info.get("_type") != "playlist":
        raise DownloadError("URL does not resolve to a playlist.")
    return [e for e in (info.get("entries") or []) if e]


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "403" in msg or "http error 403" in low:
        return (
            "YouTube returned HTTP 403 (access denied). This is usually caused "
            "by bot detection, rate limiting, or missing authentication. See "
            "the README troubleshooting section for steps to resolve it."
        )
    if "429" in msg or "http error 429" in low:
        return "Rate limited (HTTP 429). Wait a while and try again."
    if "unsupported url" in low:
        return "Unsupported or invalid URL."
    if "ffmpeg" in low or "ffprobe" in low:
        return "FFmpeg is required for this operation but is unavailable."
    if "video unavailable" in low or "this video is unavailable" in low:
        return "The video is unavailable (private, region-locked, or removed)."
    if "sign in to confirm" in low or "age" in low:
        return "This video requires sign-in or age confirmation, which is not supported."
    if "login" in low and "cookie" in low:
        return "This content requires authentication; cookies are not configured."
    return (msg or "Download failed.")[:500]
