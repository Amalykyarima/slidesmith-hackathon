import json
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
from .generator import blank_layouts, build_deck
from .previews import previews_available, render_previews
from .pptx_analysis import analyze_presentation, content_capacity, extract_style_profile
from .schemas import BuildRequest, CookRequest, GenerateRequest, SlideContent

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
    shutil.rmtree(_layouts_dir(style_id), ignore_errors=True)
    db.run("DELETE FROM styles WHERE id=?", (style_id,))


# Bump when the layout description changes, so cached ones are made again.
LAYOUTS_VERSION = 3


def _layouts_dir(style_id: str) -> Path:
    return config.PREVIEWS_DIR / "layouts" / style_id


def _render_layouts(style_id: str) -> None:
    folder = _layouts_dir(style_id)
    meta = json.loads((folder / "layouts.json").read_text())
    try:
        count = render_previews(folder / "blank.pptx", folder, width_px=1280)
        meta.update(status="ready" if count else "unavailable", count=count)
    except Exception:  # noqa: BLE001
        log.exception("Rendering the blank template failed for style %s", style_id)
        meta["status"] = "failed"
    (folder / "layouts.json").write_text(json.dumps(meta))


@app.get("/api/styles/{style_id}/layouts")
def style_layouts(style_id: str, background: BackgroundTasks):
    """The style's blank slides (cover, content, picture, section) and where their text and picture go."""
    row = db.one("SELECT * FROM styles WHERE id=?", (style_id,))
    if not row:
        raise HTTPException(404, "Style not found")
    folder = _layouts_dir(style_id)
    meta_path = folder / "layouts.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    if not meta or meta.get("version") != LAYOUTS_VERSION:
        folder.mkdir(parents=True, exist_ok=True)
        try:
            layouts = blank_layouts(Path(row["path"]), folder / "blank.pptx")
        except Exception:  # noqa: BLE001
            log.exception("Could not make the blank template for style %s", style_id)
            raise HTTPException(500, "We couldn't read the slide layouts in this style.")
        meta = {"version": LAYOUTS_VERSION, "status": "pending" if previews_available() else "unavailable", "count": 0, "layouts": layouts}
        meta_path.write_text(json.dumps(meta))
        if previews_available():
            background.add_task(_render_layouts, style_id)
    profile = db.loads(row["profile"], {})
    return {
        "status": meta["status"],
        "slide_size_in": profile.get("slide_size_in", [13.33, 7.5]),
        "background_tone": profile.get("background_tone", "light"),
        "layouts": [
            {**layout, "image": f"/files/previews/layouts/{style_id}/{n}.jpg?v={LAYOUTS_VERSION}" if n <= meta["count"] else None}
            for n, layout in enumerate(meta["layouts"], start=1)
        ],
    }


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
def _prepare(req: GenerateRequest) -> tuple[Path, dict[int, Path], dict]:
    """Checks a notes request; returns the style file, attached pictures and the style's text capacity."""
    style = db.one("SELECT * FROM styles WHERE id=?", (req.style_id,))
    if not style:
        raise HTTPException(404, "That style no longer exists. Pick another one.")

    pages = [s.page for s in req.slides]
    if len(set(pages)) != len(pages):
        raise HTTPException(400, "Each slide needs a different page number.")
    if len(pages) > config.MAX_SLIDES_PER_REQUEST:
        raise HTTPException(400, f"Please keep it to {config.MAX_SLIDES_PER_REQUEST} slides per request.")

    image_paths = _image_paths(req.slides)
    style_path = Path(style["path"])
    prs = Presentation(str(style_path))
    return style_path, image_paths, content_capacity(prs, analyze_presentation(prs))


def _image_paths(slides) -> dict[int, Path]:
    image_paths: dict[int, Path] = {}
    for spec in slides:
        if spec.image_id:
            row = db.one("SELECT * FROM images WHERE id=?", (spec.image_id,))
            if not row or not Path(row["path"]).exists():
                label = "the cover" if spec.page == 0 else f"slide {spec.page}"
                raise HTTPException(400, f"The picture for {label} was not found. Please upload it again.")
            image_paths[spec.page] = Path(row["path"])
    return image_paths


def _ask_ai(call, *args):
    """Runs an AI call, turning its failures into messages a teacher can act on."""
    try:
        return call(*args)
    except ai.AIError as exc:
        raise HTTPException(502, str(exc))
    except anthropic.AuthenticationError:
        raise HTTPException(502, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in backend/.env.")
    except anthropic.RateLimitError:
        raise HTTPException(502, "The AI service is busy right now. Please try again in a moment.")
    except anthropic.APIError as exc:
        log.exception("Anthropic API error")
        raise HTTPException(502, f"The AI service returned an error: {getattr(exc, 'message', exc)}")


def _write(req: GenerateRequest, image_paths: dict[int, Path], capacity: dict) -> tuple[list[SlideContent], str]:
    return _ask_ai(ai.generate_content, req, image_paths, capacity)


@app.post("/api/generate", status_code=201)
def generate(req: GenerateRequest, background: BackgroundTasks):
    """Notes in, finished deck out: the AI writes the text, then the deck is built."""
    if req.cover and not req.title.strip():
        raise HTTPException(400, "Give the cover slide a title.")
    style_path, image_paths, capacity = _prepare(req)
    contents, mode = _write(req, image_paths, capacity)
    if req.cover:
        contents.insert(0, SlideContent(page=0, kind="title", title=req.title.strip(), subtitle=req.subtitle.strip()))
    return _build_and_save(style_path, req.style_id, req.title, req.model_dump(), contents, image_paths, mode, background)


@app.post("/api/draft")
def draft(req: GenerateRequest):
    """The AI turns rough notes into slide text for the editor. Nothing is built."""
    _, image_paths, capacity = _prepare(req)
    contents, mode = _write(req, image_paths, capacity)
    return {"mode": mode, "slides": [c.model_dump() for c in contents]}


@app.post("/api/cook")
def cook(req: CookRequest):
    """The AI plans and writes a whole deck from a topic and description. Nothing is built yet."""
    style = db.one("SELECT * FROM styles WHERE id=?", (req.style_id,))
    if not style:
        raise HTTPException(404, "That style no longer exists. Pick another one.")
    if not req.topic.strip():
        raise HTTPException(400, "Tell us the topic of the lesson.")
    images: list[tuple[str, Path]] = []
    for image_id in dict.fromkeys(req.image_ids):
        row = db.one("SELECT * FROM images WHERE id=?", (image_id,))
        if not row or not Path(row["path"]).exists():
            raise HTTPException(400, "One of the pictures was not found. Please upload it again.")
        images.append((image_id, Path(row["path"])))
    prs = Presentation(style["path"])
    capacity = content_capacity(prs, analyze_presentation(prs))
    cover, slides, mode = _ask_ai(ai.cook, req, images, capacity)
    return {"mode": mode, "cover": cover.model_dump(), "slides": [s.model_dump() for s in slides]}


@app.post("/api/build", status_code=201)
def build(req: BuildRequest, background: BackgroundTasks):
    """Builds the slides exactly as the teacher edited them, in their style, without the AI."""
    style = db.one("SELECT * FROM styles WHERE id=?", (req.style_id,))
    if not style:
        raise HTTPException(404, "That style no longer exists. Pick another one.")
    pages = [s.page for s in req.slides]
    if len(set(pages)) != len(pages):
        raise HTTPException(400, "Each slide needs a different page number.")
    contents = [SlideContent.model_validate(s.model_dump(exclude={"image_id"})) for s in req.slides]
    cover = next((c for c in contents if c.page == 0), None)
    title = req.title.strip() or (cover.title.strip() if cover else "")
    return _build_and_save(Path(style["path"]), req.style_id, title, req.model_dump(), contents, _image_paths(req.slides), "manual", background)


def _build_and_save(
    style_path: Path,
    style_id: str,
    title: str,
    request: dict,
    contents: list[SlideContent],
    image_paths: dict[int, Path],
    mode: str,
    background: BackgroundTasks,
) -> dict:
    gen_id = uuid.uuid4().hex[:12]
    out_path = config.OUTPUTS_DIR / f"{gen_id}.pptx"
    try:
        warnings = build_deck(style_path, contents, image_paths, out_path, deck_title=title)
    except Exception:  # noqa: BLE001
        log.exception("Deck generation failed")
        out_path.unlink(missing_ok=True)
        raise HTTPException(500, "Something went wrong while building the slides. Try a different style deck or fewer slides.")

    db.run(
        "INSERT INTO generations (id, style_id, title, mode, request, slides, warnings, path, preview_status) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            gen_id,
            style_id,
            title or "Untitled slides",
            mode,
            db.dumps(request),
            db.dumps([c.model_dump() for c in contents]),
            db.dumps(warnings),
            str(out_path),
            "pending" if previews_available() else "unavailable",
        ),
    )
    if previews_available():
        background.add_task(_render_in_background, "generations", "generations", gen_id, out_path)
    return _generation_out(db.one("SELECT * FROM generations WHERE id=?", (gen_id,)))


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
