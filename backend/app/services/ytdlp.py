"""Thin service layer around ``yt-dlp`` for the v2 backend.

Nothing outside this module imports ``yt_dlp``. Routers and the worker call
these functions; every network interaction happens here.

Security notes:

* :func:`validate_media_url` rejects credentials in the URL and resolves the
  hostname, rejecting loopback, private, link-local, multicast, reserved, and
  unspecified addresses. DNS rebinding is *partially* mitigated: the resolved
  addresses are checked before yt-dlp runs, but yt-dlp performs its own DNS
  lookup afterwards, so an attacker-controlled DNS server could answer
  differently the second time. Network egress restrictions in the container
  remain the definitive control (documented in ARCHITECTURE_V2 section 11.2).
* Extracted error messages are passed through :func:`redact_sensitive` before
  they reach logs, API responses, or the database.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import yt_dlp

from ..core.config import Settings
from ..core.urls import UrlValidationError, validate_http_url

MAX_THUMBNAIL_BYTES = 10 * 1024 * 1024
THUMBNAIL_TIMEOUT_SECONDS = 15
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class DownloadError(Exception):
    """A download or metadata operation failed for a known, safe reason.

    ``code`` is a stable API error code (``invalid_url``, ``info_failed``,
    ``download_failed``, ...) and ``message`` is user-facing and redacted.
    """

    def __init__(self, message: str, code: str = "download_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        return self.message


class DownloadCancelled(Exception):
    """The download was cancelled by the user."""


ProgressCallback = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]


# ---------------------------------------------------------------------------
# yt-dlp option construction
# ---------------------------------------------------------------------------


def _base_opts(settings: Settings) -> dict[str, Any]:
    """Return hardened baseline options shared by metadata and downloads."""
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # Never load user or system yt-dlp configuration: no ``--exec`` and no
        # unexpected output templates from the host.
        "ignoreconfig": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "noplaylist": False,
        # Keep Unicode titles; storage sanitizes paths itself.
        "restrictfilenames": False,
        "windowsfilenames": False,
        # Do not persist a cache directory outside our control.
        "cachedir": False,
        "max_filesize": int(settings.max_asset_bytes),
    }


def format_spec(fmt: str) -> str:
    """Map a user-facing format profile to a yt-dlp format selector."""
    if fmt == "mp3":
        return "bestaudio/best"
    if fmt == "720p":
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    if fmt == "best":
        return "bestvideo+bestaudio/best"
    raise DownloadError("Unsupported format.", code="invalid_format")


# Kept as an alias because the v1 helper (and older internal callers) used this
# private name; both resolve to the same function.
_format_spec = format_spec


def encode_intent(fmt: str, embed_subs: bool) -> str:
    """Encode a requested format profile plus subtitle intent for storage.

    Jobs persist only ``format_selector``; the worker must reproduce the exact
    output intent after a restart. The canonical, human-readable encoding is
    ``"<format>"`` or ``"<format>+subs"`` (for example ``"720p+subs"``).
    """
    format_spec(fmt)  # validate the format name
    return f"{fmt}+subs" if embed_subs else fmt


def parse_intent(selector: str) -> tuple[str, bool]:
    """Inverse of :func:`encode_intent`; unknown values fall back to ``best``."""
    candidate = (selector or "").strip().lower()
    embed_subs = candidate.endswith("+subs")
    if embed_subs:
        candidate = candidate[: -len("+subs")]
    if candidate not in ("best", "720p", "mp3"):
        return "best", embed_subs
    return candidate, embed_subs


def _pick_thumbnail(info: dict[str, Any]) -> Optional[str]:
    thumbs = info.get("thumbnails") or []
    if not thumbs:
        return info.get("thumbnail")
    # Prefer a small/medium thumbnail; fall back to the last (largest).
    for thumb in thumbs:
        if thumb and 160 <= (thumb.get("width") or 0) <= 480:
            return thumb.get("url")
    last = thumbs[-1]
    return (last.get("url") if last else None) or info.get("thumbnail")


def _summarise_formats(formats: list[Any] | None) -> dict[str, Any]:
    heights: set[int] = set()
    has_audio = False
    for entry in formats or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("vcodec") not in (None, "none") and entry.get("height"):
            try:
                heights.add(int(entry["height"]))
            except (TypeError, ValueError):
                continue
        if entry.get("acodec") not in (None, "none"):
            has_audio = True
    return {
        "heights": sorted(heights, reverse=True),
        "has_720p": any(height >= 720 for height in heights),
        "has_audio": has_audio,
    }


def _percent(payload: dict[str, Any]) -> float:
    total = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
    downloaded = payload.get("downloaded_bytes") or 0
    if total and total > 0:
        return round(min(downloaded / total, 1.0) * 100, 1)
    return 0.0


def _make_progress_hook(
    callback: ProgressCallback, cancel: CancelCheck | None
) -> Callable[[dict[str, Any]], None]:
    def hook(payload: dict[str, Any]) -> None:
        if cancel is not None and cancel():
            raise DownloadCancelled()
        status = payload.get("status")
        if status == "downloading":
            callback(
                {
                    "status": "downloading",
                    "downloaded_bytes": payload.get("downloaded_bytes") or 0,
                    "total_bytes": payload.get("total_bytes")
                    or payload.get("total_bytes_estimate")
                    or 0,
                    "speed": payload.get("speed") or 0.0,
                    "eta": payload.get("eta") or 0.0,
                    "percent": _percent(payload),
                }
            )
        elif status == "finished":
            callback(
                {
                    "status": "processing",
                    "downloaded_bytes": payload.get("downloaded_bytes") or 0,
                    "total_bytes": payload.get("total_bytes")
                    or payload.get("total_bytes_estimate")
                    or 0,
                    "speed": payload.get("speed") or 0.0,
                    "eta": 0.0,
                    "percent": 100.0,
                }
            )

    return hook


def _check_free_space(path: Path, settings: Settings) -> None:
    """Reject a download when the target filesystem is nearly full."""
    minimum = settings.min_free_disk_mb * 1024 * 1024
    probe = path if path.exists() else path.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if free < minimum:
        raise DownloadError(
            "Not enough disk space to start the download: "
            f"{free // (1024 * 1024)} MB free, at least "
            f"{settings.min_free_disk_mb} MB required. Free up space and retry."
        )


# ---------------------------------------------------------------------------
# SSRF-aware URL validation
# ---------------------------------------------------------------------------

_RESERVED_ADDRESS_ATTRIBUTES = (
    "is_loopback",
    "is_private",
    "is_link_local",
    "is_multicast",
    "is_reserved",
    "is_unspecified",
)


def _is_rejected_address(address: Any) -> bool:
    if any(bool(getattr(address, attribute, False)) for attribute in _RESERVED_ADDRESS_ATTRIBUTES):
        return True
    # ``is_global`` also rejects shared/CGNAT space (100.64.0.0/10) and other
    # ranges that are not listed by the individual predicates above.
    return not bool(getattr(address, "is_global", True))


def validate_media_url(url: str, settings: Settings) -> str:
    """Validate a media URL and return it stripped.

    Syntax (scheme, hostname, credentials) is checked by
    :func:`backend.app.core.urls.validate_http_url`. The hostname is then
    resolved and every returned address must be globally routable unless
    ``settings.allow_private_urls`` is enabled.

    DNS rebinding is only partially mitigated, as described in the module
    docstring.
    """
    try:
        candidate = validate_http_url(url)
    except UrlValidationError as exc:
        raise DownloadError(str(exc), code="invalid_url") from exc

    parts = urlsplit(candidate)
    hostname = parts.hostname
    if not hostname:  # pragma: no cover - validate_http_url guarantees this
        raise DownloadError("The URL must include a hostname.", code="invalid_url")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:  # pragma: no cover - validate_http_url checks it
        raise DownloadError("The URL contains an invalid port.", code="invalid_url") from exc

    try:
        resolved = socket.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM
        )
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise DownloadError(
            "Could not resolve the URL host. Check the address and try again.",
            code="invalid_url",
        ) from exc
    if not resolved:
        raise DownloadError(
            "Could not resolve the URL host. Check the address and try again.",
            code="invalid_url",
        )

    if not settings.allow_private_urls:
        for entry in resolved:
            sockaddr = entry[4]
            raw_address = str(sockaddr[0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise DownloadError(
                    "The URL host resolved to an invalid address.",
                    code="invalid_url",
                ) from exc
            if _is_rejected_address(address):
                raise DownloadError(
                    "This URL points to a private or reserved network address "
                    "and is not allowed.",
                    code="invalid_url",
                )

    return candidate


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def get_info(url: str, settings: Settings) -> dict[str, Any]:
    """Return normalized metadata for a single video or playlist.

    ``extract_flat="in_playlist"`` keeps playlist previews cheap: entries are
    not resolved individually. ``playlistend`` enforces the configured item cap
    at the yt-dlp level; :func:`_normalise_info` enforces it again defensively.
    """
    target = validate_media_url(url, settings)
    opts = _base_opts(settings)
    opts.update(
        {
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "playlistend": max(1, int(settings.max_playlist_items)),
        }
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
    except DownloadError:
        raise
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(friendly_error(exc), code="info_failed") from exc
    if not isinstance(info, dict):
        raise DownloadError(
            "Could not retrieve information for this URL.", code="info_failed"
        )
    return _normalise_info(info, settings)


def _extractor_key(info: dict[str, Any], fallback: str = "") -> str:
    raw = info.get("extractor_key") or info.get("extractor") or fallback
    return str(raw or "").strip().lower()


def _canonical(extractor_key: str, media_id: str) -> str:
    key = (extractor_key or "").strip().lower()
    identifier = (media_id or "").strip()
    if not key or not identifier:
        return ""
    return f"{key}:{identifier}"


def _is_playlist(info: dict[str, Any]) -> bool:
    if info.get("_type") == "playlist":
        return True
    return info.get("entries") is not None and info.get("playlist_count") is not None


def _normalise_info(info: dict[str, Any], settings: Settings) -> dict[str, Any]:
    extractor_key = _extractor_key(info)

    if _is_playlist(info):
        media_id = str(info.get("id") or info.get("playlist_id") or "")
        raw_entries = [
            entry for entry in (info.get("entries") or []) if isinstance(entry, dict)
        ]
        limit = max(1, int(settings.max_playlist_items))
        truncated = len(raw_entries) > limit
        entries: list[dict[str, Any]] = []
        for entry in raw_entries[:limit]:
            entry_id = str(entry.get("id") or "")
            entry_key = _extractor_key(entry, extractor_key)
            entries.append(
                {
                    "id": entry_id or None,
                    "title": entry.get("title") or "",
                    "url": entry.get("url") or entry.get("webpage_url"),
                    "duration": entry.get("duration"),
                    "thumbnail": _pick_thumbnail(entry),
                    "canonical_id": _canonical(entry_key, entry_id),
                }
            )
        return {
            "type": "playlist",
            "id": media_id or None,
            "title": info.get("title") or "Untitled playlist",
            "canonical_id": _canonical(extractor_key, media_id),
            "extractor_key": extractor_key,
            "duration": info.get("duration"),
            "thumbnail": _pick_thumbnail(info),
            "webpage_url": info.get("webpage_url") or info.get("original_url"),
            "channel": info.get("uploader") or info.get("channel"),
            "formats": None,
            "entries": entries,
            "item_count": len(entries),
            "truncated": truncated,
        }

    media_id = str(info.get("id") or "")
    return {
        "type": "video",
        "id": media_id or None,
        "title": info.get("title") or "Untitled video",
        "canonical_id": _canonical(extractor_key, media_id),
        "extractor_key": extractor_key,
        "duration": info.get("duration"),
        "thumbnail": _pick_thumbnail(info),
        "webpage_url": info.get("webpage_url") or info.get("original_url"),
        "channel": info.get("uploader") or info.get("channel"),
        "formats": _summarise_formats(info.get("formats")),
        "entries": None,
        "item_count": 1,
        "truncated": False,
    }


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

_COVER_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _embed_cover_art(mp3: Path, cover: Optional[Path], album: str = "") -> bool:
    """Embed ``cover`` as the ID3 front cover of ``mp3``, in place.

    Best effort: any failure leaves the original file untouched and returns
    ``False``. ffmpeg writes a sibling temporary file which is moved over the
    original atomically.
    """
    cover_path = Path(cover) if cover else None
    if cover_path is None or not mp3.is_file():
        return False
    if not cover_path.is_file() or cover_path.suffix.lower() not in _COVER_SUFFIXES:
        return False

    tmp = mp3.with_name(f".{mp3.stem}.cover.tmp.mp3")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(mp3),
        "-i",
        str(cover_path),
        "-map",
        "0:0",
        "-map",
        "1:0",
        "-c",
        "copy",
        "-id3v2_version",
        "3",
    ]
    if album:
        cmd += ["-metadata", f"album={album}"]
    cmd += [
        "-metadata:s:v",
        "title=Album cover",
        "-metadata:s:v",
        "comment=Cover (front)",
        str(tmp),
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return False
        os.replace(tmp, mp3)
        return True
    except (OSError, subprocess.SubprocessError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _result_filepath(info: dict[str, Any]) -> Optional[str]:
    requested = info.get("requested_downloads") or []
    for item in requested:
        if isinstance(item, dict) and item.get("filepath"):
            return item["filepath"]
    return info.get("_filename") or info.get("filepath")


def download_video(
    url: str,
    fmt: str,
    embed_subs: bool,
    workdir: Path,
    progress_cb: ProgressCallback,
    cancel: CancelCheck | None,
    settings: Settings,
    album: str = "",
    cover: Optional[Path] = None,
) -> dict[str, Any]:
    """Download one video into ``workdir`` and return result metadata.

    Returns ``id``, ``title``, ``canonical_id``, ``extractor_key``,
    ``filepath``, ``thumbnail``, and ``ext``. The file is left in ``workdir``;
    the worker finalizes it into the asset directory.
    """
    target = validate_media_url(url, settings)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    _check_free_space(workdir, settings)
    if cancel is not None and cancel():
        raise DownloadCancelled()

    opts = _base_opts(settings)
    opts.update(
        {
            # A pasted "watch?v=...&list=..." URL must never pull a playlist.
            "noplaylist": True,
            "outtmpl": str(workdir / "%(id)s.%(ext)s"),
            "format": format_spec(fmt),
            "progress_hooks": [_make_progress_hook(progress_cb, cancel)],
        }
    )

    postprocessors: list[dict[str, Any]] = []

    if fmt == "mp3":
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        )
        if album:
            # FFmpegExtractAudio resolves the ``ffmpeg`` key of
            # ``postprocessor_args``, so its invocation writes the album tag.
            opts["postprocessor_args"] = {
                "ffmpeg": ["-metadata", f"album={album}"],
            }
    else:
        opts["merge_output_format"] = "mp4"

    if embed_subs:
        opts.update(
            {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en"],
                "embedsubtitles": True,
            }
        )
        postprocessors.append(
            {
                "key": "FFmpegEmbedSubtitle",
                "already_have_subtitle": False,
            }
        )

    if postprocessors:
        opts["postprocessors"] = postprocessors

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=True)
    except DownloadCancelled:
        raise
    except yt_dlp.utils.DownloadError as exc:
        if cancel is not None and cancel():
            raise DownloadCancelled() from exc
        raise DownloadError(friendly_error(exc)) from exc

    if not isinstance(info, dict):
        raise DownloadError("Download produced no result.")

    filepath = _result_filepath(info)
    if not filepath or not Path(filepath).is_file():
        raise DownloadError("The download finished but no file was produced.")

    if fmt == "mp3":
        # Best effort: a failed artwork embed must leave the download intact.
        _embed_cover_art(Path(filepath), cover, album)

    return {
        "id": info.get("id"),
        "title": info.get("title") or "download",
        "canonical_id": _canonical(_extractor_key(info), str(info.get("id") or "")),
        "extractor_key": _extractor_key(info),
        "filepath": filepath,
        "thumbnail": _pick_thumbnail(info),
        "ext": Path(filepath).suffix.lstrip("."),
    }


def download_thumbnail(
    url: str, dest: Path, settings: Settings
) -> bool:
    """Download ``url`` to ``dest`` with a size cap, returning success.

    Best effort by design: failures never raise, a partial ``.part`` file is
    removed, and an existing ``dest`` is only replaced after a complete read.
    """
    destination = Path(dest)
    partial = destination.with_name(destination.name + ".part")
    try:
        validate_media_url(url, settings)
        limit = min(MAX_THUMBNAIL_BYTES, max(1, int(settings.max_asset_bytes)))
        request = urllib.request.Request(
            url, headers={"User-Agent": _BROWSER_USER_AGENT}
        )
        with urllib.request.urlopen(
            request, timeout=THUMBNAIL_TIMEOUT_SECONDS
        ) as response:
            data = response.read(limit + 1)
        if not data or len(data) > limit:
            raise ValueError("Empty or oversized thumbnail.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(data)
        os.replace(partial, destination)
        return True
    except Exception:  # noqa: BLE001 - thumbnails are strictly best effort
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# Safe error messages
# ---------------------------------------------------------------------------

# Sensitive material that must never reach logs or API responses: URL
# userinfo, HTTP auth/cookie headers, and credential-bearing query parameters.
_URL_USERINFO_RE = re.compile(r"(https?://)[^/@\s]+@")
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(cookie|set-cookie|authorization|proxy-authorization)\s*:\s*[^\r\n]+"
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)\b(cookie|authorization|auth|token|access_token|api_key|apikey|"
    r"signature|sig|password|passwd|secret|session|key)[=:]([^&\s\"']+)"
)

_NETWORK_ERROR_PHRASES = (
    "failed to resolve",
    "name or service not known",
    "temporary failure in name resolution",
    "getaddrinfo",
    "connection refused",
    "connection reset",
    "connection aborted",
    "network is unreachable",
    "no route to host",
    "timed out",
    "timeout",
    "ssl:",
    "tls handshake",
    "certificate_verify_failed",
    "certificate verify failed",
)


def redact_sensitive(text: str) -> str:
    """Strip credentials/cookies from a message before it is surfaced or logged."""
    if not text:
        return text
    text = _URL_USERINFO_RE.sub(r"\1", text)
    text = _AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}: ***", text)
    return _SENSITIVE_QUERY_RE.sub(lambda match: f"{match.group(1)}=***", text)


def friendly_error(exc: Exception) -> str:
    """Translate a raw yt-dlp error into an actionable, redacted message."""
    msg = str(exc)
    low = msg.lower()
    if re.search(r"\b403\b", msg) or "forbidden" in low:
        return (
            "The site denied access (HTTP 403). This is usually caused by bot "
            "detection, rate limiting, or missing authentication. Try again "
            "later or use a different source."
        )
    if re.search(r"\b429\b", msg):
        return "Rate limited (HTTP 429). Wait a while and try again."
    if "no space left" in low or "enospc" in low or "disk quota exceeded" in low:
        return (
            "Not enough disk space to complete the download. "
            "Free up space and try again."
        )
    if "unsupported url" in low:
        return "Unsupported or invalid URL."
    if "ffmpeg" in low or "ffprobe" in low:
        return "FFmpeg is required for this operation but is unavailable."
    if any(phrase in low for phrase in _NETWORK_ERROR_PHRASES):
        return (
            "Network error while contacting the site. Check your connection "
            "and try again."
        )
    if "video unavailable" in low or "this video is unavailable" in low:
        return "The video is unavailable (private, region-locked, or removed)."
    if any(
        phrase in low
        for phrase in (
            "sign in to confirm",
            "confirm your age",
            "age-restricted",
            "age restricted",
            "inappropriate for some users",
        )
    ):
        return "This video requires sign-in or age confirmation, which is not supported."
    if "login" in low and "cookie" in low:
        return "This content requires authentication; cookies are not configured."
    return redact_sensitive(msg or "Download failed.")[:500]
