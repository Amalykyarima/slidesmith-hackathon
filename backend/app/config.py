import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "storage"))
STYLES_DIR = STORAGE_DIR / "styles"
IMAGES_DIR = STORAGE_DIR / "images"
OUTPUTS_DIR = STORAGE_DIR / "outputs"
PREVIEWS_DIR = STORAGE_DIR / "previews"
DB_PATH = STORAGE_DIR / "slidesmith.db"

for d in (STYLES_DIR, IMAGES_DIR, OUTPUTS_DIR, PREVIEWS_DIR):
    d.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:4200").split(",") if o.strip()]

MAX_STYLE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_SLIDES_PER_REQUEST = 40


def find_soffice() -> str | None:
    explicit = os.getenv("SOFFICE_BIN", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


SOFFICE = find_soffice()
AI_ENABLED = bool(ANTHROPIC_API_KEY)
