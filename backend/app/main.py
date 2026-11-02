import logging
import time
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pptx import Presentation

from . import ai, auth, config, db
from .auth import owner
from .generator import build_deck
from .previews import previews_available, render_previews
from .pptx_analysis import analyze_presentation, content_capacity, extract_style_profile, style_roles
from .schemas import BuildRequest, GenerateRequest, RebuildRequest, SlideContent

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
app.add_middleware(auth.AuthMiddleware)
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
        "preview_status": row["preview_status"],
        # ?v= changes on every rebuild, so browsers fetch the new thumbnails.
        "previews": [f"{u}?v={row.get('rev') or 0}" for u in _preview_urls("generations", row["id"], row["preview_count"])],
        "rev": row.get("rev") or 0,
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
        "auth_required": config.AUTH_ENABLED,
    }


@app.get("/api/session")
def session():
    return {"auth_required": config.AUTH_ENABLED, "name": owner() or None}


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@app.post("/api/login")
def login(payload: dict, request: Request, response: Response):
    if not config.AUTH_ENABLED:
        return {"name": None}
    name = auth.name_for_code(str(payload.get("code", "")))
    if not name:
        time.sleep(0.5)  # slow down guessing
        raise HTTPException(401, "That access code isn't right. Check it and try again.")
    response.set_cookie(
        auth.COOKIE, auth.make_token(name), max_age=auth.MAX_AGE,
        httponly=True, samesite="lax", secure=_secure(request), path="/",
    )
    return {"name": name}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    response.delete_cookie(auth.COOKIE, path="/", secure=_secure(request), httponly=True, samesite="lax")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Styles
# --------------------------------------------------------------------------- #
@app.get("/api/styles")
def list_styles():
    return [_style_out(r) for r in db.many("SELECT * FROM styles WHERE owner=? ORDER BY created_at DESC, rowid DESC", (owner(),))]


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
        "INSERT INTO styles (id, name, filename, path, profile, preview_status, owner) VALUES (?,?,?,?,?,?,?)",
        (style_id, display_name, filename, str(path), db.dumps(profile), "pending" if previews_available() else "unavailable", owner()),
    )
    if previews_available():
        background.add_task(_render_in_background, "styles", "styles", style_id, path)
    return _style_out(db.one("SELECT * FROM styles WHERE id=? AND owner=?", (style_id, owner())))


@app.get("/api/styles/{style_id}")
def get_style(style_id: str):
    row = db.one("SELECT * FROM styles WHERE id=? AND owner=?", (style_id, owner()))
    if not row:
        raise HTTPException(404, "Style not found")
    return _style_out(row)


@app.patch("/api/styles/{style_id}")
def rename_style(style_id: str, payload: dict):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Name can't be empty")
    if not db.one("SELECT id FROM styles WHERE id=? AND owner=?", (style_id, owner())):
        raise HTTPException(404, "Style not found")
    db.run("UPDATE styles SET name=? WHERE id=?", (name[:80], style_id))
    return _style_out(db.one("SELECT * FROM styles WHERE id=? AND owner=?", (style_id, owner())))


@app.delete("/api/styles/{style_id}", status_code=204)
def delete_style(style_id: str):
    row = db.one("SELECT * FROM styles WHERE id=? AND owner=?", (style_id, owner()))
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
        "INSERT INTO images (id, filename, path, width, height, owner) VALUES (?,?,?,?,?,?)",
        (image_id, file.filename or path.name, str(path), width, height, owner()),
    )
    return {"id": image_id, "filename": file.filename, "width": width, "height": height, "url": f"/files/images/{path.name}"}


@app.delete("/api/images/{image_id}", status_code=204)
def delete_image(image_id: str):
    row = db.one("SELECT * FROM images WHERE id=? AND owner=?", (image_id, owner()))
    if row:
        Path(row["path"]).unlink(missing_ok=True)
        db.run("DELETE FROM images WHERE id=?", (image_id,))


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _load_style(style_id: str) -> dict:
    style = db.one("SELECT * FROM styles WHERE id=? AND owner=?", (style_id, owner()))
    if not style:
        raise HTTPException(404, "That style no longer exists. Pick another one.")
    return style


def _check_pages(pages: list[int]) -> None:
    if len(set(pages)) != len(pages):
        raise HTTPException(400, "Each slide needs a different page number.")
    if len(pages) > config.MAX_SLIDES_PER_REQUEST:
        raise HTTPException(400, f"Please keep it to {config.MAX_SLIDES_PER_REQUEST} slides per request.")


def _image_paths(slides) -> dict[int, Path]:
    paths: dict[int, Path] = {}
    for spec in slides:
        if spec.image_id:
            row = db.one("SELECT * FROM images WHERE id=? AND owner=?", (spec.image_id, owner()))
            if not row:
                raise HTTPException(400, f"The image for page {spec.page} was not found. Please upload it again.")
            paths[spec.page] = Path(row["path"])
    return paths


def _build_and_record(
    style: dict,
    title: str,
    request_dump: dict,
    contents: list[SlideContent],
    image_paths: dict[int, Path],
    mode: str,
    background: BackgroundTasks,
) -> dict:
    """Pour finished slide content into the style, save the deck, start previews."""
    gen_id = uuid.uuid4().hex[:12]
    out_path = config.OUTPUTS_DIR / f"{gen_id}.pptx"
    try:
        warnings = build_deck(Path(style["path"]), contents, image_paths, out_path, deck_title=title)
    except Exception:  # noqa: BLE001
        log.exception("Deck generation failed")
        out_path.unlink(missing_ok=True)
        raise HTTPException(500, "Something went wrong while building the slides. Try a different style deck or fewer slides.")

    db.run(
        "INSERT INTO generations (id, style_id, title, mode, request, slides, warnings, path, preview_status, owner) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            gen_id,
            style["id"],
            title or "Untitled slides",
            mode,
            db.dumps(request_dump),
            db.dumps([c.model_dump() for c in contents]),
            db.dumps(warnings),
            str(out_path),
            "pending" if previews_available() else "unavailable",
            owner(),
        ),
    )
    if previews_available():
        background.add_task(_render_in_background, "generations", "generations", gen_id, out_path)
    return _generation_out(db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner())))


@app.post("/api/generate", status_code=201)
def generate(req: GenerateRequest, background: BackgroundTasks):
    """Teacher's rough notes -> AI (or demo mode) writes the slides -> deck."""
    style = _load_style(req.style_id)
    _check_pages([s.page for s in req.slides])
    image_paths = _image_paths(req.slides)

    prs = Presentation(str(Path(style["path"])))
    infos = analyze_presentation(prs)
    capacity = {**content_capacity(prs, infos), "roles": style_roles(prs, infos)}

    if config.AI_ENABLED and config.AI_DAILY_LIMIT:
        used = db.one(
            "SELECT COUNT(*) AS n FROM generations WHERE owner=? AND mode='ai' AND date(created_at)=date('now')",
            (owner(),),
        )["n"]
        if used >= config.AI_DAILY_LIMIT:
            raise HTTPException(
                429,
                f"You've used today's {config.AI_DAILY_LIMIT} AI generations. Tick \"Use my text exactly (no AI)\" "
                "to keep building today, or try again tomorrow.",
            )

    try:
        contents, mode = ai.generate_content(req, image_paths, capacity)
    except anthropic.AuthenticationError:
        raise HTTPException(502, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in backend/.env.")
    except anthropic.RateLimitError:
        raise HTTPException(502, "The AI service is busy right now. Please try again in a moment.")
    except anthropic.APIError as exc:
        log.exception("Anthropic API error")
        raise HTTPException(502, f"The AI service returned an error: {getattr(exc, 'message', exc)}")

    images_by_page = {s.page: s.image_id for s in req.slides}
    for c in contents:
        c.image_id = images_by_page.get(c.page)
    return _build_and_record(style, req.title, req.model_dump(), contents, image_paths, mode, background)


@app.post("/api/build", status_code=201)
def build_exact(req: BuildRequest, background: BackgroundTasks):
    """Finished slide content -> deck, word for word. No AI call, no credit used."""
    style = _load_style(req.style_id)
    _check_pages([s.page for s in req.slides])
    image_paths = _image_paths(req.slides)
    contents = [SlideContent(**s.model_dump()) for s in sorted(req.slides, key=lambda s: s.page)]
    return _build_and_record(style, req.title, req.model_dump(), contents, image_paths, "exact", background)


@app.post("/api/generations/{gen_id}/rebuild")
def rebuild_generation(gen_id: str, req: RebuildRequest, background: BackgroundTasks):
    """Rebuild a generated deck after the teacher edited it. No AI call: the text is used as written."""
    row = db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner()))
    if not row:
        raise HTTPException(404, "That deck no longer exists. Generate it again.")
    style = db.one("SELECT * FROM styles WHERE id=? AND owner=?", (row["style_id"], owner()))
    if not style:
        raise HTTPException(404, "The style for this deck is gone (the server may have restarted). Upload it again and rebuild the deck.")
    _check_pages([s.page for s in req.slides])
    image_paths = _image_paths(req.slides)
    contents = [SlideContent(**s.model_dump()) for s in sorted(req.slides, key=lambda s: s.page)]
    title = row["title"] if req.title is None else (req.title.strip() or "Untitled slides")

    out_path = Path(row["path"])
    tmp_path = out_path.with_name(f"{out_path.stem}.rebuild.pptx")
    try:
        warnings = build_deck(Path(style["path"]), contents, image_paths, tmp_path, deck_title=title)
    except Exception:  # noqa: BLE001
        log.exception("Rebuild failed")
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(500, "Something went wrong while rebuilding the slides. Your previous version is unchanged.")
    tmp_path.replace(out_path)

    db.run(
        "UPDATE generations SET title=?, slides=?, warnings=?, request=?, rev=rev+1, preview_status=?, preview_count=0 "
        "WHERE id=? AND owner=?",
        (
            title,
            db.dumps([c.model_dump() for c in contents]),
            db.dumps(warnings),
            db.dumps(req.model_dump()),
            "pending" if previews_available() else "unavailable",
            gen_id,
            owner(),
        ),
    )
    if previews_available():
        background.add_task(_render_in_background, "generations", "generations", gen_id, out_path)
    return _generation_out(db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner())))


@app.get("/api/styles/{style_id}/samples")
def style_samples(style_id: str):
    """The style's sample slides, for the editor's layout picker."""
    style = db.one("SELECT * FROM styles WHERE id=? AND owner=?", (style_id, owner()))
    if not style:
        raise HTTPException(404, "Style not found")
    infos = analyze_presentation(Presentation(str(Path(style["path"]))))
    out = []
    for info in infos:
        if info.complex or info.title_id is None:
            continue  # can't be refilled safely
        n = info.index + 1
        out.append({
            "index": info.index,
            "number": n,
            "kind": info.kind,
            "role": info.role,
            "title": info.preview_text,
            "has_body": info.body_id is not None,
            "has_picture": bool(info.picture_ids),
            "preview": f"/files/previews/styles/{style_id}/{n}.jpg" if n <= style["preview_count"] else None,
        })
    return out


@app.get("/api/generations")
def list_generations():
    rows = db.many("SELECT * FROM generations WHERE owner=? ORDER BY created_at DESC, rowid DESC LIMIT 20", (owner(),))
    return [_generation_out(r) for r in rows]


@app.get("/api/generations/{gen_id}")
def get_generation(gen_id: str):
    row = db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner()))
    if not row:
        raise HTTPException(404, "Not found")
    return _generation_out(row)


@app.get("/api/generations/{gen_id}/download")
def download_generation(gen_id: str):
    row = db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner()))
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "File not found")
    return FileResponse(row["path"], media_type=PPTX_MIME, filename=f"{_slugify(row['title'] or '')}.pptx")


# --------------------------------------------------------------------------- #
# The Angular app (production: one service serves both the API and the pages)
# --------------------------------------------------------------------------- #
@app.get("/{full_path:path}", include_in_schema=False)
def frontend(full_path: str):
    dist = config.FRONTEND_DIST.resolve()
    if full_path.startswith(("api/", "files/")) or not (dist / "index.html").exists():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    candidate = (dist / full_path).resolve()
    if full_path and candidate.is_file() and dist in candidate.parents:
        return FileResponse(candidate)
    # Client-side routes (/styles, /create, /login) all load the app shell.
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
