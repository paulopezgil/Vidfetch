"""Library listing, file resolution, and deletion helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote

from .. import database
from ..config import settings

VIDEO_EXT = {"mp4", "mkv", "webm", "avi", "mov", "m4v", "flv", "ts", "mpg", "mpeg"}
AUDIO_EXT = {"mp3", "m4a", "aac", "wav", "flac", "ogg", "opus"}
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT


def _thumb_url(video_id: str) -> Optional[str]:
    if not video_id:
        return None
    candidate = settings.thumb_dir / f"{video_id}.jpg"
    if candidate.exists():
        return f"/api/thumb/{quote(video_id)}.jpg"
    return None


def resolve_file(filename: str) -> Optional[Path]:
    """Resolve a requested filename to an authorised file inside the output dir.

    Returns ``None`` unless ``filename`` is a bare filename (no path
    separators) that resolves, after symlink expansion, to an existing regular
    file directly inside the download directory.
    """
    if not filename or Path(filename).name != filename:
        return None
    if filename.startswith("."):
        return None
    path = (settings.download_dir / filename).resolve()
    if path.parent != settings.download_dir:
        return None
    if not path.is_file():
        return None
    return path


def list_media_files() -> list[dict]:
    files: list[dict] = []
    for p in settings.download_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if name.startswith("."):
            continue
        ext = p.suffix.lower().lstrip(".")
        if ext not in MEDIA_EXT:
            continue
        owner = database.find_file_owner(name) or {}
        video_id = owner.get("video_id", "")
        stat = p.stat()
        files.append({
            "filename": name,
            "title": owner.get("title") or name,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "ext": ext,
            "media_type": "audio" if ext in AUDIO_EXT else "video",
            "thumbnail_url": _thumb_url(video_id),
            "video_id": video_id,
            "playlist_id": database.find_item_by_filename(name),
        })
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return files


def list_playlists() -> list[dict]:
    out: list[dict] = []
    for p in database.list_playlists():
        thumb = p.get("thumbnail_path") or ""
        thumb_url = None
        if thumb and (settings.thumb_dir / thumb).exists():
            thumb_url = f"/api/thumb/{quote(thumb)}"
        out.append({
            "playlist_id": p["playlist_id"],
            "url": p["url"],
            "title": p["title"],
            "channel": p.get("channel") or "",
            "thumbnail_url": thumb_url,
            "item_count": p["item_count"],
            "total_size": p.get("total_size") or 0,
            "zip_path": p.get("zip_path") or "",
            "status": p.get("status") or "pending",
            "created_at": p["created_at"],
            "updated_at": p["updated_at"],
        })
    return out


def build_library() -> dict:
    return {"files": list_media_files(), "playlists": list_playlists()}


def playlist_detail(playlist_id: str) -> Optional[dict]:
    p = database.get_playlist(playlist_id)
    if not p:
        return None
    items = database.get_playlist_items(playlist_id)
    item_out: list[dict] = []
    downloaded = failed = 0
    for it in items:
        status = it["status"]
        if status == "downloaded":
            if it["filename"] and (settings.download_dir / it["filename"]).exists():
                downloaded += 1
            else:
                status = "missing"
        elif status == "failed":
            failed += 1
        item_out.append({
            "index": it["item_index"],
            "video_id": it.get("video_id") or "",
            "url": it["url"],
            "title": it["title"],
            "duration": it.get("duration"),
            "status": status,
            "filename": it.get("filename") or "",
            "size": it.get("size") or 0,
            "error": it.get("error") or "",
        })

    thumb = p.get("thumbnail_path") or ""
    thumb_url = None
    if thumb and (settings.thumb_dir / thumb).exists():
        thumb_url = f"/api/thumb/{quote(thumb)}"

    return {
        "playlist_id": p["playlist_id"],
        "url": p["url"],
        "title": p["title"],
        "channel": p.get("channel") or "",
        "thumbnail_url": thumb_url,
        "item_count": len(item_out),
        "total_size": p.get("total_size") or 0,
        "zip_path": p.get("zip_path") or "",
        "status": p.get("status") or "pending",
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "items": item_out,
        "downloaded_count": downloaded,
        "failed_count": failed,
    }


def delete_file(filename: str) -> Optional[dict]:
    """Delete a file and reconcile DB references. History records are kept."""
    path = resolve_file(filename)
    if path is None:
        return None

    result = {"filename": filename, "deleted": False, "was_zip": False,
              "playlist_id": ""}

    if path.suffix.lower() == ".zip":
        result["was_zip"] = True
        for p in database.list_playlists():
            if p.get("zip_path") == filename:
                result["playlist_id"] = p["playlist_id"]
                database.upsert_playlist({
                    **p,
                    "zip_path": "",
                    "updated_at": database.iso_now(),
                })

    # If the file belongs to a playlist item, clear its reference so it can be
    # re-downloaded. History is intentionally left untouched.
    item = database.get_item_by_filename(filename)
    if item:
        database.update_playlist_item_status(
            item["playlist_id"], item["url"], "pending", "", 0, ""
        )

    path.unlink(missing_ok=True)
    result["deleted"] = True
    return result
