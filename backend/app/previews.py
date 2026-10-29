"""Slide thumbnails via LibreOffice (pptx -> pdf) + PyMuPDF (pdf -> jpg).

Optional: if LibreOffice isn't installed the app still works, it just can't show previews.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
from pathlib import Path

import pymupdf

from . import config

log = logging.getLogger("slidesmith.previews")
_lock = threading.Lock()  # LibreOffice doesn't like parallel conversions


def previews_available() -> bool:
    return config.SOFFICE is not None


def render_previews(pptx_path: Path, out_dir: Path, max_pages: int = 40, width_px: int = 640) -> int:
    """Renders slide thumbnails to out_dir/1.jpg, 2.jpg ... Returns how many were written."""
    if not config.SOFFICE:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        old.unlink()

    with _lock, tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "lo-profile"
        cmd = [
            config.SOFFICE,
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            tmp,
            str(pptx_path),
        ]
        subprocess.run(cmd, check=True, timeout=240, capture_output=True)
        pdf_path = Path(tmp) / f"{Path(pptx_path).stem}.pdf"
        if not pdf_path.exists():
            raise RuntimeError("LibreOffice did not produce a PDF")

        count = 0
        with pymupdf.open(pdf_path) as doc:
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                zoom = width_px / page.rect.width
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                pix.save(str(out_dir / f"{i + 1}.jpg"), jpg_quality=80)
                count += 1
        return count
