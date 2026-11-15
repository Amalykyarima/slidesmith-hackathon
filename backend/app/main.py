import logging
import threading
import time
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pptx import Presentation

from . import agents, ai, auth, config, db, levels, pictos, sen
from .auth import owner
from .generator import build_deck
from .previews import previews_available, render_into, render_previews
from .pptx_analysis import (
    analyze_presentation, content_capacity, extract_style_profile, one_off_slides, style_roles, template_catalogue,
)
from .schemas import BuildRequest, GenerateRequest, SlideContent, SlideEdits
from . import scene, storage, videos

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("slidesmith")

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF", "WEBP", "BMP", "MPO"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.startup()  # bring back saved work before the database is opened
    db.init_db()
    agents.init_db()
    sen.init_db()
    log.info("AI mode: %s | previews: %s", "claude" if config.AI_ENABLED else "MOCK", previews_available())
    yield
    storage.shutdown()  # last save before the server sleeps


app = FastAPI(title="SlideSmith API", lifespan=lifespan)
app.add_middleware(auth.AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sen.router)
app.mount("/files/previews", StaticFiles(directory=config.PREVIEWS_DIR), name="previews")
app.mount("/files/images", StaticFiles(directory=config.IMAGES_DIR), name="images")
if pictos.PICTO_DIR.exists():
    app.mount("/files/pictos", StaticFiles(directory=pictos.PICTO_DIR), name="pictos")


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
        # Her sample slides she switched off (1-based): never copied, never offered to the AI.
        "excluded": db.loads(row.get("excluded") or "[]", []),
    }


# Slides whose thumbnails are being redrawn after an edit (one server process, so memory is fine).
_updating: dict[str, set[int]] = {}
_state_lock = threading.Lock()
# One lock per deck, shared by the "all editor backgrounds" pass and single-slide renders,
# so a background is never drawn twice at the same time.
_bg_locks: dict[str, threading.Lock] = {}


def _bg_lock(gen_id: str) -> threading.Lock:
    with _state_lock:
        return _bg_locks.setdefault(gen_id, threading.Lock())


def _bg_file(gen_id: str, number: int) -> Path:
    return config.PREVIEWS_DIR / "generations" / gen_id / "bg" / str(number) / "1.jpg"


def _generation_out(row: dict) -> dict:
    revs = db.loads(row.get("slide_revs") or "{}", {})
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
        # ?v= changes when that slide's thumbnail is redrawn after an edit, so the
        # browser fetches just that one again.
        "previews": [f"{u}?v={revs.get(str(n), 0)}" for n, u in
                     enumerate(_preview_urls("generations", row["id"], row["preview_count"]), 1)],
        "updating": sorted(_updating.get(row["id"], ())),  # slides whose thumbnail is being redrawn
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


def _render_backgrounds(gen_id: str, pptx_path: Path, numbers: list[int]) -> None:
    """Editor backgrounds for many slides in one LibreOffice run (starting LibreOffice is
    most of the cost), so opening a slide in the editor is instant."""
    import tempfile

    with _bg_lock(gen_id):
        todo = [n for n in numbers if not _bg_file(gen_id, n).exists()]
        if not todo:
            return
        try:
            with tempfile.TemporaryDirectory() as tmp:
                deck = Path(tmp) / "backgrounds.pptx"
                scene.slides_copy(pptx_path, todo, deck, strip=True)
                render_into(deck, [_bg_file(gen_id, n) for n in todo], width_px=1280)
        except Exception:  # noqa: BLE001
            log.exception("Editor backgrounds failed for %s", gen_id)


def _render_generation(gen_id: str, pptx_path: Path) -> None:
    """Thumbnails first (the teacher is waiting for them), then the editor backgrounds."""
    _render_in_background("generations", "generations", gen_id, pptx_path)
    row = db.one("SELECT preview_count FROM generations WHERE id=?", (gen_id,))
    if row and row["preview_count"]:
        _render_backgrounds(gen_id, pptx_path, list(range(1, row["preview_count"] + 1)))


def _redraw_slide(gen_id: str, pptx_path: Path, number: int) -> None:
    """After an edit: redraw only that slide's thumbnail, then publish its new version."""
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "slide.pptx"
            scene.slides_copy(pptx_path, [number], one, strip=False)
            render_into(one, [config.PREVIEWS_DIR / "generations" / gen_id / f"{number}.jpg"], width_px=640)
        with _state_lock:
            row = db.one("SELECT slide_revs FROM generations WHERE id=?", (gen_id,))
            if row:
                revs = db.loads(row["slide_revs"] or "{}", {})
                revs[str(number)] = revs.get(str(number), 0) + 1
                db.run("UPDATE generations SET slide_revs=? WHERE id=?", (db.dumps(revs), gen_id))
    except Exception:  # noqa: BLE001
        log.exception("Redrawing slide %s of %s failed", number, gen_id)
    finally:
        with _state_lock:
            _updating.get(gen_id, set()).discard(number)


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
        "storage": storage.status(),
        "levels": levels.public(),
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
        excluded = one_off_slides(analyze_presentation(Presentation(str(path))))
    except Exception:  # noqa: BLE001
        log.exception("Could not read uploaded deck")
        path.unlink(missing_ok=True)
        raise HTTPException(400, "We couldn't read that PowerPoint file. Try re-saving it as .pptx and upload again.")

    display_name = name.strip() or Path(filename).stem
    db.run(
        "INSERT INTO styles (id, name, filename, path, profile, preview_status, owner, excluded) VALUES (?,?,?,?,?,?,?,?)",
        (style_id, display_name, filename, str(path), db.dumps(profile), "pending" if previews_available() else "unavailable",
         owner(), db.dumps(excluded)),
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
def update_style(style_id: str, payload: dict):
    """Rename a style and/or choose which of its sample slides may be used."""
    row = db.one("SELECT * FROM styles WHERE id=? AND owner=?", (style_id, owner()))
    if not row:
        raise HTTPException(404, "Style not found")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "Name can't be empty")
        db.run("UPDATE styles SET name=? WHERE id=?", (name[:80], style_id))
    if "excluded" in payload:
        count = db.loads(row["profile"], {}).get("slide_count", 0)
        raw = payload.get("excluded")
        if not isinstance(raw, list) or not all(isinstance(n, int) for n in raw):
            raise HTTPException(400, "excluded must be a list of slide numbers")
        chosen = sorted({n for n in raw if 1 <= n <= count})
        if count and len(chosen) >= count:
            raise HTTPException(400, "Keep at least one slide in use.")
        db.run("UPDATE styles SET excluded=? WHERE id=?", (db.dumps(chosen), style_id))
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


def _labels(req, from_ai: dict) -> dict[str, str]:
    """Her LO / Keywords lines: what the teacher typed wins, else what the AI wrote."""
    return {k: (getattr(req, k, "") or "").strip() or from_ai.get(k, "") for k in ("lo", "keywords")}


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


def _video_links(slides, image_paths: dict[int, Path]) -> dict[int, str]:
    """Checked video link per page. A page with a link but no picture gets the video's
    thumbnail as its picture (added to image_paths)."""
    links: dict[int, str] = {}
    for spec in slides:
        if not (spec.video_url or "").strip():
            continue
        try:
            links[spec.page] = videos.clean_url(spec.video_url)
        except ValueError as err:
            raise HTTPException(400, f"Page {spec.page}: {err}")
        if spec.page not in image_paths:
            image_paths[spec.page] = videos.thumbnail(links[spec.page])
    return links


def _build_and_record(
    style: dict,
    title: str,
    request_dump: dict,
    contents: list[SlideContent],
    image_paths: dict[int, Path],
    mode: str,
    background: BackgroundTasks,
    video_links: dict[int, str] | None = None,
    lesson_date=None,
    lesson_labels: dict[str, str] | None = None,
) -> dict:
    """Pour finished slide content into the style, save the deck, start previews."""
    gen_id = uuid.uuid4().hex[:12]
    out_path = config.OUTPUTS_DIR / f"{gen_id}.pptx"
    try:
        warnings = build_deck(Path(style["path"]), contents, image_paths, out_path, deck_title=title, videos=video_links, lesson_date=lesson_date,
                               lesson_labels=lesson_labels,
                               skip=set(db.loads(style.get("excluded") or "[]", [])))
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
        background.add_task(_render_generation, gen_id, out_path)
    return _generation_out(db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner())))


def _capacity(style: dict) -> dict:
    prs = Presentation(str(Path(style["path"])))
    skip = set(db.loads(style.get("excluded") or "[]", []))
    infos = [i for i in analyze_presentation(prs) if i.index + 1 not in skip] or analyze_presentation(prs)
    return {**content_capacity(prs, infos), "roles": style_roles(prs, infos),
            "catalogue": template_catalogue(prs, infos)}


def _check_ai_limit() -> None:
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


@app.post("/api/generate", status_code=201)
def generate(req: GenerateRequest, background: BackgroundTasks):
    """Teacher's rough notes -> AI (or demo mode) writes the slides -> deck."""
    style = _load_style(req.style_id)
    _check_pages([s.page for s in req.slides])
    image_paths = _image_paths(req.slides)
    video_links = _video_links(req.slides, image_paths)
    capacity = _capacity(style)
    _check_ai_limit()

    try:
        extras: dict[str, str] = {}
        contents, mode = ai.generate_content(req, image_paths, capacity, extras)
    except anthropic.AuthenticationError:
        raise HTTPException(502, "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in backend/.env.")
    except anthropic.RateLimitError:
        raise HTTPException(502, "The AI service is busy right now. Please try again in a moment.")
    except anthropic.APIError as exc:
        log.exception("Anthropic API error")
        raise HTTPException(502, f"The AI service returned an error: {getattr(exc, 'message', exc)}")
    except RuntimeError as exc:  # the AI answered without slides, twice
        raise HTTPException(502, str(exc))

    # A whole lesson is named after its topic: the AI's name for it, else the topic's first line.
    title = req.title.strip()
    if req.whole_lesson:
        title = extras.get("deck_title") or req.brief.strip().splitlines()[0][:120]
    return _build_and_record(style, title, req.model_dump(mode="json"), contents, image_paths, mode, background, video_links, req.lesson_date,
                             _labels(req, extras))


@app.post("/api/build", status_code=201)
def build_exact(req: BuildRequest, background: BackgroundTasks):
    """Finished slide content -> deck, word for word. No AI call, no credit used."""
    style = _load_style(req.style_id)
    _check_pages([s.page for s in req.slides])
    image_paths = _image_paths(req.slides)
    video_links = _video_links(req.slides, image_paths)
    contents = [
        SlideContent(**s.model_dump(exclude={"image_id", "video_url"}))
        for s in sorted(req.slides, key=lambda s: s.page)
    ]
    return _build_and_record(style, req.title, req.model_dump(mode="json"), contents, image_paths, "exact", background, video_links, req.lesson_date,
                             _labels(req, {}))



# --------------------------------------------------------------------------- #
# Agent runs: Orchestrator -> Planner -> SEN Adapter -> Reviewer -> (teacher) -> Builder
# --------------------------------------------------------------------------- #
class _ThreadTasks:
    """BackgroundTasks for work started outside a request (agent threads)."""

    def add_task(self, fn, *args, **kwargs):
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


@app.get("/api/levels")
def list_levels():
    return levels.public()


def _own_run(run_id: str) -> dict:
    run = agents.get(run_id, owner())
    if not run:
        raise HTTPException(404, "That run no longer exists. Start again.")
    return run


@app.post("/api/runs", status_code=201)
def start_run(req: GenerateRequest):
    """Start the agent team. Watch it on /api/runs/{id}/events."""
    style = _load_style(req.style_id)
    _check_pages([s.page for s in req.slides])
    image_paths = _image_paths(req.slides)
    video_links = _video_links(req.slides, image_paths)
    capacity = _capacity(style)
    _check_ai_limit()

    def builder(run: dict, contents: list[SlideContent]) -> dict:
        st = run["state"]
        mode = st.get("ai_mode", "ai")
        return _build_and_record(style, st.get("title", ""), {**req.model_dump(mode="json"), "run_id": run["id"]},
                                 contents, image_paths, mode, _ThreadTasks(), video_links, req.lesson_date,
                                 {"lo": st.get("lo", ""), "keywords": st.get("keywords", "")})

    run = agents.create(req, owner())
    _builders[run["id"]] = builder
    agents.start(run, req, image_paths, capacity, builder)
    return agents.public(run)


# Builders for live runs, so the teacher's approval builds with the same style and pictures.
_builders: dict[str, object] = {}


@app.get("/api/runs")
def list_runs():
    rows = db.many("SELECT id FROM runs WHERE owner=? ORDER BY created_at DESC, rowid DESC LIMIT 20", (owner(),))
    return [agents.public(agents.get(r["id"], owner())) for r in rows]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    return agents.public(_own_run(run_id))


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str, after: int = 0):
    """Server-sent events: every agent step as it happens. Ends when the run stops or waits."""
    run = _own_run(run_id)

    def stream():
        sent = after
        idle = 0
        while True:
            events = run["events"]
            while sent < len(events):
                ev = events[sent]
                sent += 1
                yield f"id: {ev['n']}\nevent: agent\ndata: {db.dumps(ev)}\n\n"
            if run["status"] in ("built", "failed", "needs_review") and sent >= len(run["events"]):
                yield f"event: end\ndata: {db.dumps({'status': run['status']})}\n\n"
                return
            idle += 1
            if idle % 50 == 0:
                yield ": keep-alive\n\n"
            if idle > 3000:  # ~10 minutes
                return
            time.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/runs/{run_id}/approve")
def approve_run(run_id: str, payload: dict):
    """Human-in-the-loop: the teacher edits flagged slides and approves; then the deck is built."""
    run = _own_run(run_id)
    if run["status"] != "needs_review":
        raise HTTPException(409, "This run isn't waiting for review.")
    builder = _builders.get(run_id)
    if builder is None:
        raise HTTPException(410, "The server restarted since this run started. Please run it again.")
    slides = payload.get("slides") or []
    accepted = payload.get("accepted") or []
    if not isinstance(slides, list) or not isinstance(accepted, list):
        raise HTTPException(400, "slides and accepted must be lists")
    try:
        generation = agents.approve(run, [s for s in slides if isinstance(s, dict)], accepted, builder)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"run": agents.public(run), "generation": generation}


@app.post("/api/supports")
def make_supports(payload: dict):
    """Visual supports straight from a topic (no deck): Now/Next, timetable, steps, key words."""
    topic = str(payload.get("topic") or "").strip()[:200]
    details = str(payload.get("details") or "").strip()[:3000]
    if not topic and not details:
        raise HTTPException(400, "Say what the lesson or activity is about.")
    try:
        return agents.supports_from_topic(topic, details, str(payload.get("level") or ""))
    except Exception as exc:  # noqa: BLE001
        log.exception("Visual supports failed")
        raise HTTPException(502, agents._friendly(exc))


# --------------------------------------------------------------------------- #
# Live avatar: a LiveKit room the Synthesia avatar worker joins
# --------------------------------------------------------------------------- #
@app.get("/api/avatar")
def avatar_status():
    return {"configured": config.AVATAR_ENABLED}


@app.post("/api/avatar/token")
def avatar_token(payload: dict):
    """A room for staff and the avatar. "debrief": talk after a lesson to draft an assess-plan-do-review record;
    "build": talk to make a lesson; "present": teach a deck."""
    if not config.AVATAR_ENABLED:
        raise HTTPException(503, "The live avatar isn't set up on this server (LiveKit keys and AVATAR_SECRET).")
    from datetime import timedelta

    from livekit import api as lk

    mode = payload.get("mode") if payload.get("mode") in ("debrief", "build", "present") else "debrief"
    meta = {"mode": mode, "owner": owner(), "level": levels.get(payload.get("level")).key}
    if mode == "present":
        gen_id = str(payload.get("generation_id") or "")
        if not db.one("SELECT id FROM generations WHERE id=? AND owner=?", (gen_id, owner())):
            raise HTTPException(404, "Choose a deck to present.")
        meta["generation_id"] = gen_id
    room = f"slidesmith-{uuid.uuid4().hex[:10]}"
    token = (
        lk.AccessToken(config.LIVEKIT_API_KEY, config.LIVEKIT_API_SECRET)
        .with_identity(f"teacher-{uuid.uuid4().hex[:6]}")
        .with_name(owner() or "Teacher")
        .with_ttl(timedelta(minutes=15))
        .with_grants(lk.VideoGrants(room_join=True, room=room, can_publish_data=True))
        .with_room_config(lk.RoomConfiguration(
            sync_streams=True,
            agents=[lk.RoomAgentDispatch(agent_name=config.AVATAR_AGENT_NAME, metadata=db.dumps(meta))],
        ))
        .to_jwt()
    )
    return {"url": config.LIVEKIT_URL, "token": token, "room": room, "mode": mode}


@app.get("/api/pictos/search")
def picto_search(q: str = ""):
    return pictos.search(q)


@app.get("/api/pictos/match")
def picto_match(word: str = ""):
    return pictos.symbol(word)


# --------------------------------------------------------------------------- #
# On-slide editing
# --------------------------------------------------------------------------- #
def _own_generation(gen_id: str) -> dict:
    row = db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner()))
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "That deck no longer exists (the server may have restarted). Generate it again.")
    return row


@app.get("/api/generations/{gen_id}/slides/{number}")
def slide_scene(gen_id: str, number: int):
    """Slide `number` as editable pieces, plus a picture of everything else on it."""
    row = _own_generation(gen_id)
    path = Path(row["path"])
    try:
        model = scene.describe_slide(path, number)
    except IndexError:
        raise HTTPException(404, "That slide doesn't exist.")
    rev = row.get("rev") or 0
    # The background picture comes from its own endpoint so the slide opens straight away.
    background = f"/files/previews/generations/{gen_id}/bg/{number}/1.jpg" if _bg_file(gen_id, number).exists() else None
    for shape in model["shapes"]:
        if shape["kind"] == "picture":
            shape["src"] = f"/api/generations/{gen_id}/slides/{number}/pictures/{shape['id']}?v={rev}"
    return {**model, "background": background, "background_pending": background is None and previews_available(), "rev": rev}


@app.get("/api/generations/{gen_id}/slides/{number}/background")
def slide_background(gen_id: str, number: int):
    """Waits until slide `number`'s editor background exists (drawing it if needed)."""
    row = _own_generation(gen_id)
    if number < 1:
        raise HTTPException(404, "That slide doesn't exist.")
    if previews_available() and not _bg_file(gen_id, number).exists():
        _render_backgrounds(gen_id, Path(row["path"]), [number])
    url = f"/files/previews/generations/{gen_id}/bg/{number}/1.jpg" if _bg_file(gen_id, number).exists() else None
    return {"background": url}


@app.get("/api/generations/{gen_id}/slides/{number}/pictures/{shape_id}")
def slide_picture(gen_id: str, number: int, shape_id: int):
    row = _own_generation(gen_id)
    try:
        data, mime = scene.picture_bytes(Path(row["path"]), number, shape_id)
    except (IndexError, KeyError):
        raise HTTPException(404, "Picture not found")
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/generations/{gen_id}/slides/{number}")
def edit_slide(gen_id: str, number: int, edits: SlideEdits, background: BackgroundTasks):
    """Save moves, resizes and text formatting made on the slide."""
    row = _own_generation(gen_id)
    path = Path(row["path"])
    work = path.with_name(f"{path.stem}.editing.pptx")
    shutil.copyfile(path, work)
    try:
        scene.apply_edits(work, number, [e.model_dump(exclude_none=True) for e in edits.shapes])
    except IndexError:
        work.unlink(missing_ok=True)
        raise HTTPException(404, "That slide doesn't exist.")
    except Exception:  # noqa: BLE001
        log.exception("Saving slide edits failed")
        work.unlink(missing_ok=True)
        raise HTTPException(500, "Something went wrong while saving. Your slide is unchanged.")
    work.replace(path)
    db.run("UPDATE generations SET rev=rev+1 WHERE id=? AND owner=?", (gen_id, owner()))
    if previews_available() and number <= (row["preview_count"] or 0):
        with _state_lock:
            _updating.setdefault(gen_id, set()).add(number)
        background.add_task(_redraw_slide, gen_id, path, number)
    return _generation_out(db.one("SELECT * FROM generations WHERE id=? AND owner=?", (gen_id, owner())))


@app.get("/api/generations")
def list_generations():
    rows = db.many("SELECT * FROM generations WHERE owner=? ORDER BY created_at DESC, rowid DESC LIMIT 20", (owner(),))
    return [_generation_out(r) for r in rows]


@app.post("/api/generations/{gen_id}/previews")
def redraw_previews(gen_id: str, background: BackgroundTasks):
    """Previews failed or took too long: draw them again."""
    row = _own_generation(gen_id)
    if not previews_available():
        raise HTTPException(400, "Previews need LibreOffice on the server.")
    db.run("UPDATE generations SET preview_status='pending' WHERE id=?", (gen_id,))
    background.add_task(_render_generation, gen_id, Path(row["path"]))
    return _generation_out(db.one("SELECT * FROM generations WHERE id=?", (gen_id,)))


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
