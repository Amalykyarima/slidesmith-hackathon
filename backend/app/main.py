import logging
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pptx import Presentation

from . import ai, config, db
from .generator import build_deck
from .previews import previews_available, render_previews
from .pptx_analysis import analyze_presentation, content_capacity, extract_style_profile
from .schemas import GenerateRequest, RebuildRequest, SlideContent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("slidesmith")

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF", "WEBP", "BMP", "MPO"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    log.info("AI mode: %s | previews: %s", "claude" if config.AI_ENABLED else "MOCK", previews_available())
    yield


app = FastAPI(title="SlideSmith API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/files/previews", StaticFiles(directory=config.PREVIEWS_DIR), name="previews")
app.mount("/files/images", StaticFiles(directory=config.IMAGES_DIR), name="images")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _preview_urls(kind: str, entity_id: str, count: int) -> list[str]:
    return [f"/files/previews/{kind}/{entity_id}/{n}.jpg" for n in range(1, count + 1)]


def _style_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "filename": row["filename"],
        "created_at": row["created_at"],
        "profile": db.loads(row["profile"], {}),
        "preview_status": row["preview_status"],
        "previews": _preview_urls("styles", row["id"], row["preview_count"]),
    }


def _generation_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "mode": row["mode"],
        "style_id": row["style_id"],
        "created_at": row["created_at"],
        "slides": db.loads(row["slides"], []),
        "warnings": db.loads(row["warnings"], []),
        "download_url": f"/api/generations/{row['id']}/download",
        "image_pages": [sl["page"] for sl in db.loads(row["request"], {}).get("slides", []) if sl.get("image_id")],
        "preview_status": row["preview_status"],
        "previews": _preview_urls("generations", row["id"], row["preview_count"]),
    }


def _slugify(text: str, fallback: str = "slides") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug[:60] or fallback


def _render_in_background(table: str, kind: str, entity_id: str, pptx_path: Path) -> None:
    try:
        count = render_previews(pptx_path, config.PREVIEWS_DIR / kind / entity_id)
        status = "ready" if count else "unavailable"
        db.run(f"UPDATE {table} SET preview_status=?, preview_count=? WHERE id=?", (status, count, entity_id))
    except Exception:  # noqa: BLE001
        log.exception("Preview rendering failed for %s %s", kind, entity_id)
        db.run(f"UPDATE {table} SET preview_status='failed' WHERE id=?", (entity_id,))


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "ai_enabled": config.AI_ENABLED,
        "model": config.CLAUDE_MODEL if config.AI_ENABLED else None,
        "previews_enabled": previews_available(),
    }


# --------------------------------------------------------------------------- #
# Styles
# --------------------------------------------------------------------------- #
@app.get("/api/styles")
def list_styles():
    return [_style_out(r) for r in db.many("SELECT * FROM styles ORDER BY created_at DESC, rowid DESC")]


@app.post("/api/styles", status_code=201)
def upload_style(background: BackgroundTasks, file: UploadFile = File(...), name: str = Form("")):
    filename = file.filename or "style.pptx"
    if not filename.lower().endswith(".pptx"):
        raise HTTPException(400, "Please upload a PowerPoint file ending in .pptx (in PowerPoint: File > Save As > .pptx).")
    data = file.file.read(config.MAX_STYLE_BYTES + 1)
    if len(data) > config.MAX_STYLE_BYTES:
        raise HTTPException(413, "That file is too large (max 40 MB).")
    if not data.startswith(b"PK"):
        raise HTTPException(400, "That doesn't look like a valid .pptx file.")

    style_id = uuid.uuid4().hex[:12]
    path = config.STYLES_DIR / f"{style_id}.pptx"
    path.write_bytes(data)
    try:
        profile = extract_style_profile(path)
    except Exception:  # noqa: BLE001
        log.exception("Could not read uploaded deck")
        path.unlink(missing_ok=True)
        raise HTTPException(400, "We couldn't read that PowerPoint file. Try re-saving it as .pptx and upload again.")

    display_name = name.strip() or Path(filename).stem
    db.run(
        "INSERT INTO styles (id, name, filename, path, profile, preview_status) VALUES (?,?,?,?,?,?)",
        (style_id, display_name, filename, str(path), db.dumps(profile), "pending" if previews_available() else "unavailable"),
    )
    if previews_available():
        background.add_task(_render_in_background, "styles", "styles", style_id, path)
    return _style_out(db.one("SELECT * FROM styles WHERE id=?", (style_id,)))


@app.get("/api/styles/{style_id}")
def get_style(style_id: str):
    row = db.one("SELECT * FROM styles WHERE id=?", (style_id,))
    if not row:
        raise HTTPException(404, "Style not found")
    return _style_out(row)


@app.patch("/api/styles/{style_id}")
def rename_style(style_id: str, payload: dict):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Name can't be empty")
    if not db.one("SELECT id FROM styles WHERE id=?", (style_id,)):
        raise HTTPException(404, "Style not found")
    db.run("UPDATE styles SET name=? WHERE id=?", (name[:80], style_id))
    return _style_out(db.one("SELECT * FROM styles WHERE id=?", (style_id,)))


@app.delete("/api/styles/{style_id}", status_code=204)
def delete_style(style_id: str):
    row = db.one("SELECT * FROM styles WHERE id=?", (style_id,))
    if not row:
        raise HTTPException(404, "Style not found")
    Path(row["path"]).unlink(missing_ok=True)
    shutil.rmtree(config.PREVIEWS_DIR / "styles" / style_id, ignore_errors=True)
    db.run("DELETE FROM styles WHERE id=?", (style_id,))


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
@app.post("/api/images", status_code=201)
def upload_image(file: UploadFile = File(...)):
    data = file.file.read(config.MAX_IMAGE_BYTES + 1)
    if len(data) > config.MAX_IMAGE_BYTES:
        raise HTTPException(413, "That image is too large (max 15 MB).")
    image_id = uuid.uuid4().hex[:12]
    try:
        import io

        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ALLOWED_IMAGE_FORMATS:
                raise ValueError("unsupported")
            im = ImageOps.exif_transpose(im)
            im.thumbnail((2000, 2000))
            has_alpha = im.mode in ("RGBA", "LA", "P")
            if has_alpha:
                im = im.convert("RGBA")
                ext = "png"
            else:
                im = im.convert("RGB")
                ext = "jpg"
            path = config.IMAGES_DIR / f"{image_id}.{ext}"
            im.save(path, format="PNG" if ext == "png" else "JPEG", **({} if ext == "png" else {"quality": 88}))
            width, height = im.size
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "That file isn't a supported image (use PNG, JPG, GIF or WEBP).")

    db.run(
        "INSERT INTO images (id, filename, path, width, height) VALUES (?,?,?,?,?)",
        (image_id, file.filename or path.name, str(path), width, height),
    )
    return {"id": image_id, "filename": file.filename, "width": width, "height": height, "url": f"/files/images/{path.name}"}


@app.delete("/api/images/{image_id}", status_code=204)
def delete_image(image_id: str):
    row = db.one("SELECT * FROM images WHERE id=?", (image_id,))
    if row:
        Path(row["path"]).unlink(missing_ok=True)
        db.run("DELETE FROM images WHERE id=?", (image_id,))


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
@app.post("/api/generate", status_code=201)
def generate(req: GenerateRequest, background: BackgroundTasks):
    style = db.one("SELECT * FROM styles WHERE id=?", (req.style_id,))
    if not style:
        raise HTTPException(404, "That style no longer exists. Pick another one.")

    pages = [s.page for s in req.slides]
    if len(set(pages)) != len(pages):
        raise HTTPException(400, "Each slide needs a different page number.")
    if len(pages) > config.MAX_SLIDES_PER_REQUEST:
        raise HTTPException(400, f"Please keep it to {config.MAX_SLIDES_PER_REQUEST} slides per request.")
    if req.cover and not req.title.strip():
        raise HTTPException(400, "Give the cover slide a title.")

    image_paths: dict[int, Path] = {}
    for spec in req.slides:
        if spec.image_id:
            row = db.one("SELECT * FROM images WHERE id=?", (spec.image_id,))
            if not row:
                raise HTTPException(400, f"The image for page {spec.page} was not found. Please upload it again.")
            image_paths[spec.page] = Path(row["path"])

    style_path = Path(style["path"])
    prs = Presentation(str(style_path))
    capacity = content_capacity(prs, analyze_presentation(prs))

    try:
        contents, mode = ai.generate_content(req, image_paths, capacity)
    except anthropic.AuthenticationError:
        raise HTTPException(502, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in backend/.env.")
    except anthropic.RateLimitError:
        raise HTTPException(502, "The AI service is busy right now. Please try again in a moment.")
    except anthropic.APIError as exc:
        log.exception("Anthropic API error")
        raise HTTPException(502, f"The AI service returned an error: {getattr(exc, 'message', exc)}")
    if req.cover:
        contents.insert(0, SlideContent(page=0, kind="title", title=req.title.strip(), subtitle=req.subtitle.strip()))

    return _build_and_save(style_path, req, contents, image_paths, mode, background)


def _build_and_save(
    style_path: Path,
    req: GenerateRequest,
    contents: list[SlideContent],
    image_paths: dict[int, Path],
    mode: str,
    background: BackgroundTasks,
) -> dict:
    gen_id = uuid.uuid4().hex[:12]
    out_path = config.OUTPUTS_DIR / f"{gen_id}.pptx"
    try:
        warnings = build_deck(style_path, contents, image_paths, out_path, deck_title=req.title)
    except Exception:  # noqa: BLE001
        log.exception("Deck generation failed")
        out_path.unlink(missing_ok=True)
        raise HTTPException(500, "Something went wrong while building the slides. Try a different style deck or fewer slides.")

    db.run(
        "INSERT INTO generations (id, style_id, title, mode, request, slides, warnings, path, preview_status) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            gen_id,
            req.style_id,
            req.title or "Untitled slides",
            mode,
            db.dumps(req.model_dump()),
            db.dumps([c.model_dump() for c in contents]),
            db.dumps(warnings),
            str(out_path),
            "pending" if previews_available() else "unavailable",
        ),
    )
    if previews_available():
        background.add_task(_render_in_background, "generations", "generations", gen_id, out_path)
    return _generation_out(db.one("SELECT * FROM generations WHERE id=?", (gen_id,)))


@app.post("/api/generations/{gen_id}/rebuild", status_code=201)
def rebuild_generation(gen_id: str, body: RebuildRequest, background: BackgroundTasks):
    """Builds the teacher's edited slides again, in the same style, without calling the AI."""
    row = db.one("SELECT * FROM generations WHERE id=?", (gen_id,))
    if not row:
        raise HTTPException(404, "Those slides no longer exist. Generate them again.")
    style = db.one("SELECT * FROM styles WHERE id=?", (row["style_id"],))
    if not style:
        raise HTTPException(404, "The style these slides used was deleted, so they can't be rebuilt.")
    req = GenerateRequest.model_validate(db.loads(row["request"]))

    known = {s.page for s in req.slides} | ({0} if req.cover else set())
    pages = [s.page for s in body.slides]
    if len(set(pages)) != len(pages) or not set(pages) <= known:
        raise HTTPException(400, "The edited slides don't match the original deck. Refresh and try again.")

    image_paths: dict[int, Path] = {}
    for spec in req.slides:
        img = db.one("SELECT * FROM images WHERE id=?", (spec.image_id,)) if spec.image_id else None
        if img and Path(img["path"]).exists():
            image_paths[spec.page] = Path(img["path"])
    return _build_and_save(Path(style["path"]), req, list(body.slides), image_paths, row["mode"], background)


@app.get("/api/generations")
def list_generations():
    rows = db.many("SELECT * FROM generations ORDER BY created_at DESC, rowid DESC LIMIT 20")
    return [_generation_out(r) for r in rows]


@app.get("/api/generations/{gen_id}")
def get_generation(gen_id: str):
    row = db.one("SELECT * FROM generations WHERE id=?", (gen_id,))
    if not row:
        raise HTTPException(404, "Not found")
    return _generation_out(row)


@app.get("/api/generations/{gen_id}/download")
def download_generation(gen_id: str):
    row = db.one("SELECT * FROM generations WHERE id=?", (gen_id,))
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "File not found")
    return FileResponse(row["path"], media_type=PPTX_MIME, filename=f"{_slugify(row['title'] or '')}.pptx")
