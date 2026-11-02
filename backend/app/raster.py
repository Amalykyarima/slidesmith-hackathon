"""PDF pages -> JPG thumbnails, run as its own short-lived process:

    python -m app.raster <pdf> <out_dir> <width_px> <max_pages>

PyMuPDF adds ~140 MB the moment it's imported. Keeping it out of the web server
process matters on a 512 MB host; this process exits and gives the memory back.
"""
from __future__ import annotations

import sys
from pathlib import Path


def rasterize(pdf_path: Path, out_dir: Path, width_px: int, max_pages: int) -> int:
    import pymupdf

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


if __name__ == "__main__":
    pdf, out, width, limit = sys.argv[1:5]
    print(rasterize(Path(pdf), Path(out), int(width), int(limit)))
