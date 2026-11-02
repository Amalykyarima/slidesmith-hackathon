"""Slide thumbnails via LibreOffice (pptx -> pdf) + PyMuPDF (pdf -> jpg).

Optional: if LibreOffice isn't installed the app still works, it just can't show previews.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
from pathlib import Path

import gc
import sys

from . import config

log = logging.getLogger("slidesmith.previews")
_lock = threading.Lock()  # LibreOffice doesn't like parallel conversions


def previews_available() -> bool:
    return config.SOFFICE is not None


def release_memory() -> None:
    """Hand freed memory back to the system (glibc keeps it otherwise)."""
    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # not glibc (e.g. macOS): nothing to do


def _first_slides(pptx_path: Path, tmp: Path, limit: int) -> Path:
    """On small servers, preview only the first `limit` slides: LibreOffice needed
    ~675 MB for a 70-slide deck, more than a 512 MB free instance has."""
    if limit <= 0:
        return pptx_path
    from pptx import Presentation

    prs = Presentation(str(pptx_path))
    ids = prs.slides._sldIdLst
    if len(ids) <= limit:
        return pptx_path
    for sld_id in list(ids)[limit:]:
        prs.part.drop_rel(sld_id.rId)
        ids.remove(sld_id)
    trimmed = tmp / f"{pptx_path.stem}.pptx"
    prs.save(str(trimmed))
    return trimmed


def _to_jpgs(pptx_path: Path, tmp: Path, out_dir: Path, width_px: int, max_pages: int) -> int:
    """pptx -> pdf (LibreOffice) -> out_dir/1.jpg, 2.jpg ... Caller holds _lock."""
    profile = tmp / "lo-profile"
    cmd = [
        config.SOFFICE,
        f"-env:UserInstallation={profile.as_uri()}",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(tmp),
        str(pptx_path),
    ]
    subprocess.run(cmd, check=True, timeout=240, capture_output=True)
    pdf_path = tmp / f"{Path(pptx_path).stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError("LibreOffice did not produce a PDF")
    # Separate process: PyMuPDF costs ~140 MB just to import (see raster.py).
    done = subprocess.run(
        [sys.executable, "-m", "app.raster", str(pdf_path), str(out_dir), str(width_px), str(max_pages)],
        check=True, timeout=120, capture_output=True, text=True, cwd=str(config.BASE_DIR),
    )
    return int(done.stdout.strip() or 0)


def render_previews(pptx_path: Path, out_dir: Path, max_pages: int = 40, width_px: int = 640) -> int:
    """Renders slide thumbnails to out_dir/1.jpg, 2.jpg ... Returns how many were written."""
    if not config.SOFFICE:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    release_memory()  # the request that built the deck is done; free its memory before LibreOffice starts
    with _lock, tempfile.TemporaryDirectory() as tmp:
        pptx_path = _first_slides(Path(pptx_path), Path(tmp), config.PREVIEW_MAX_SLIDES)
        pages = Path(tmp) / "pages"
        pages.mkdir()
        count = _to_jpgs(pptx_path, Path(tmp), pages, width_px, max_pages)
        for old in out_dir.glob("*.jpg"):
            old.unlink()
        for n in range(1, count + 1):
            (pages / f"{n}.jpg").replace(out_dir / f"{n}.jpg")
        return count


def render_into(pptx_path: Path, targets: list[Path], width_px: int) -> int:
    """Renders page i of the deck to targets[i-1] (each swapped in whole, so a page being
    viewed never shows half-written). Returns how many were written."""
    if not config.SOFFICE or not targets:
        return 0
    release_memory()
    with _lock, tempfile.TemporaryDirectory() as tmp:
        pages = Path(tmp) / "pages"
        pages.mkdir()
        count = _to_jpgs(Path(pptx_path), Path(tmp), pages, width_px, len(targets))
        for n, target in enumerate(targets[:count], 1):
            target.parent.mkdir(parents=True, exist_ok=True)
            (pages / f"{n}.jpg").replace(target)
        return count
