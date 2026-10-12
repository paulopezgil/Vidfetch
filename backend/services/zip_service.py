"""ZIP packaging for completed playlist downloads."""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional


def create_zip(
    files: Iterable[Path],
    dest: Path,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> None:
    """Create a ZIP archive at ``dest`` containing ``files``.

    Media files are already compressed by their codecs, so ``ZIP_STORED`` is
    used: it is dramatically faster and produces archives of nearly the same
    size. The archive is written to a temporary ``.part`` file first and then
    atomically renamed so a partially written archive is never exposed.
    """
    files = [Path(f) for f in files if f and Path(f).is_file()]
    if not files:
        raise ValueError("No files available to package.")

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")

    total = sum(f.stat().st_size for f in files)
    written = 0

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
            for f in files:
                zf.write(f, arcname=f.name)
                written += f.stat().st_size
                if progress_cb and total:
                    progress_cb(min(written / total, 1.0))
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    os.replace(tmp, dest)
