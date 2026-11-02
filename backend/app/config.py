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

# --------------------------------------------------------------------------- #
# Hosting
# --------------------------------------------------------------------------- #
def _parse_codes(raw: str) -> dict[str, str]:
    """ "Mrs Khan:maple-42, Mr Lee:river-7" -> {"maple-42": "Mrs Khan", "river-7": "Mr Lee"}.
    A code without a name ("maple-42") signs in as "Teacher"."""
    codes: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, code = item.rpartition(":")
        code = code.strip()
        if code:
            codes[code] = (name.strip() if sep else "") or "Teacher"
    return codes


# Teachers sign in with an access code. Empty = no login (local development).
ACCESS_CODES = _parse_codes(os.getenv("ACCESS_CODES", ""))
AUTH_ENABLED = bool(ACCESS_CODES)
# Signs the login cookie. Set it on the host so sign-ins survive restarts.
SECRET_KEY = os.getenv("SECRET_KEY", "").strip() or os.urandom(32).hex()
# Small hosts (Render free: 512 MB) can't preview a 70-slide deck in one go.
# 0 = no limit. Only the first N slides of a deck get thumbnails.
PREVIEW_MAX_SLIDES = int(os.getenv("PREVIEW_MAX_SLIDES", "0") or 0)
# Most AI generations one teacher can run per day. 0 = no limit.
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "0") or 0)
# Built Angular app, served by FastAPI in production (one service, one address).
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist" / "frontend" / "browser"))
