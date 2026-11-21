"""Path-safe local media storage.

All persisted media lives under a single root (the ``DOWNLOAD_DIR`` volume).
Asset rows store *relative* paths; every path that crosses this module is
resolved and checked to remain under the root. Absolute paths, ``..`` segments,
NUL bytes, Windows separators, and symlinks escaping the root are rejected.

Finalization is atomic on the same filesystem (``os.replace``), with a
copy-and-replace fallback for the rare cross-device case.
"""
from __future__ import annotations

import errno
import os
import re
import shutil
from pathlib import Path, PurePosixPath

from .filenames import sanitize_filename

_ASSET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EXTENSION_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class StorageError(ValueError):
    """Raised for unsafe paths or invalid storage operations."""


class Storage:
    """Root-scoped storage helper."""

    def __init__(self, root: Path | str) -> None:
        raw = str(root).strip() if root is not None else ""
        if not raw:
            raise StorageError("A storage root path is required.")
        self.root = Path(raw).expanduser().resolve()

    # -- directories --------------------------------------------------------

    def ensure_directories(self) -> Path:
        """Create the root and its working subdirectories (idempotent)."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "assets").mkdir(parents=True, exist_ok=True)
        (self.root / ".tmp").mkdir(parents=True, exist_ok=True)
        return self.root

    def free_bytes(self) -> int:
        """Free bytes on the filesystem holding the storage root."""
        target = self.root
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(target)
        return int(usage.free)

    def asset_dir(self, asset_id: str) -> Path:
        """Return the per-asset directory (not created)."""
        return self.root / "assets" / self._validate_asset_id(asset_id)

    def final_path(
        self,
        asset_id: str,
        title: str,
        canonical_id: str,
        extension: str,
    ) -> Path:
        """Build the final, sanitized file path for a ready asset."""
        directory = self.asset_dir(asset_id)
        ext = self._normalize_extension(extension)
        stem = sanitize_filename(title, max_len=100)
        canonical = sanitize_filename(canonical_id, max_len=40).replace(" ", "_")
        filename = f"{stem} [{canonical}].{ext}"
        return directory / filename

    # -- validation ---------------------------------------------------------

    @staticmethod
    def _validate_asset_id(asset_id: str) -> str:
        if not isinstance(asset_id, str):
            raise StorageError("asset_id must be a string.")
        candidate = asset_id.strip()
        if (
            not candidate
            or candidate in (".", "..")
            or not _ASSET_ID_RE.fullmatch(candidate)
        ):
            raise StorageError("Invalid asset id.")
        return candidate

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        if not isinstance(extension, str):
            raise StorageError("extension must be a string.")
        candidate = extension[1:] if extension.startswith(".") else extension
        if not _EXTENSION_RE.fullmatch(candidate):
            raise StorageError("Invalid file extension.")
        return candidate.lower()

    def _ensure_within_root(self, path: Path | str, label: str) -> Path:
        raw = str(path).strip()
        if not raw:
            raise StorageError(f"{label} path is required.")
        try:
            resolved = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            raise StorageError(f"Unable to resolve {label.lower()} path.") from exc
        if resolved != self.root and self.root not in resolved.parents:
            raise StorageError(f"{label} must be inside the storage root.")
        return resolved

    def validate_relative_path(self, rel: str | Path) -> Path:
        """Validate a stored relative path and return its resolved location.

        Rejects absolute paths, parent traversal, NUL bytes, backslashes, drive
        prefixes, and symlinks that resolve outside the storage root.
        """
        if isinstance(rel, Path):
            raw = str(rel)
        elif isinstance(rel, str):
            raw = rel
        else:
            raise StorageError("Path must be a string or Path.")

        raw = raw.strip()
        if not raw:
            raise StorageError("Path is required.")
        if "\x00" in raw:
            raise StorageError("Path contains a NUL byte.")
        if "\\" in raw:
            raise StorageError("Path must use forward slashes.")
        if raw.startswith("/") or _DRIVE_RE.match(raw):
            raise StorageError("Absolute paths are not allowed.")

        pure = PurePosixPath(raw)
        parts = pure.parts
        if not parts:
            raise StorageError("Path is required.")
        if any(part == ".." for part in parts):
            raise StorageError("Path traversal is not allowed.")

        candidate = self.root.joinpath(*parts)
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise StorageError("Unable to resolve path safely.") from exc
        if resolved != self.root and self.root not in resolved.parents:
            raise StorageError("Path escapes the storage root.")
        return resolved

    # -- file operations ----------------------------------------------------

    def atomic_finalize(self, src: Path | str, dest: Path | str) -> Path:
        """Move ``src`` to ``dest`` atomically, creating parent directories.

        Both paths must live under the storage root. Returns the resolved
        destination path.
        """
        source = self._ensure_within_root(src, "Source")
        destination = self._ensure_within_root(dest, "Destination")
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        if not source.is_file():
            raise IsADirectoryError(f"Source is not a file: {source}")
        if source == destination:
            raise StorageError("Source and destination are the same file.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(source, destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            temp = destination.with_name(destination.name + ".tmp")
            try:
                with source.open("rb") as read_file, temp.open("wb") as write_file:
                    shutil.copyfileobj(read_file, write_file)
                    write_file.flush()
                    os.fsync(write_file.fileno())
                os.replace(temp, destination)
            finally:
                if temp.exists():
                    temp.unlink()
            source.unlink()
        return destination.resolve()

    def delete_asset_file(self, rel: str | Path) -> bool:
        """Delete a stored file by relative path.

        Returns ``True`` when a file was removed and ``False`` when it did not
        exist. Symlinks and directories are refused.
        """
        resolved = self.validate_relative_path(rel)
        lexical = self.root.joinpath(*PurePosixPath(str(rel).strip()).parts)
        if lexical.is_symlink():
            raise StorageError("Refusing to delete a symlink.")
        if resolved.is_dir():
            raise IsADirectoryError("Refusing to delete a directory.")
        if not resolved.exists():
            return False
        lexical.unlink()
        return True
