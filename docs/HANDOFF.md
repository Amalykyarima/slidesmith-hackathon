# SlideSmith: project handoff

Paste or upload this file at the start of a new project/chat, together with `slidesmith.zip` (the code). It contains everything decided and built so far.

## 1. The idea
A web app for school teachers who produce daily slides. Origin: the owner is a teaching assistant at a secondary school and a teacher asked for her daily slides to be automated.

Requirements, as originally stated:
1. Teachers upload sample slide decks (as many as they want, different styles). These samples define the style for future slides. Teachers can remove them and upload new ones at any time.
2. A section where the teacher enters what they want on the slides, per page number, then submits.
3. A section to upload images for specific pages.
4. Web app first. Goal was a demo the next day, then collect improvement feedback.

Owner's background: frontend engineer (Angular), studying towards AI/ML engineering. Preferred stack was Angular + Python.

## 2. Core design decision
The AI does **not** learn or imitate the style. Style is taken from the teacher's own sample slides, and the AI only writes text.

1. **Analyse** each uploaded .pptx: classify every sample slide as `title`, `content`, `image` or `section`, and find the title shape, body shape and large pictures.
2. **Generate**: for each requested page, **clone** the best-matching sample slide inside the teacher's own file, replace its text (and picture), then delete the original samples. Fonts, colours, backgrounds and positions carry over because they are the teacher's own slides.
3. **AI step**: Claude returns structured JSON (page, kind, title, subtitle, bullets, notes) via a forced tool call. It never touches PowerPoint. It also receives attached images (as vision input) so text can fit the picture.
4. **Mock mode**: with no API key the app builds slides from the teacher's notes as typed, so the whole flow runs offline.

## 3. Stack
- **Backend:** Python, FastAPI, python-pptx, Pydantic, SQLite (stdlib), Pillow, Anthropic SDK, PyMuPDF. LibreOffice (optional) for thumbnails.
- **Frontend:** Angular 21 (standalone components, signals, zoneless, new control flow `@if/@for/@let`), plain CSS with design tokens, lazy-loaded routes. Dev proxy `/api` and `/files` to port 8000 via `proxy.conf.json`.
- **Storage:** local disk under `backend/storage/` plus SQLite. Planned move: S3 + Postgres.

## 4. Project layout
```
slidesmith/
  README.md  SETUP.md  .gitignore
  backend/
    requirements.txt  pytest.ini  .env.example
    app/
      main.py            # FastAPI routes
      config.py          # env, paths, soffice detection
      db.py              # sqlite helpers (styles, images, generations)
      schemas.py         # SlideSpec, GenerateRequest, SlideContent
      pptx_analysis.py   # slide classification + style profile extraction
      generator.py       # clone sample slide, fill text/pictures, fit text, build deck
      ai.py              # Claude tool-use call + mock mode
      previews.py        # pptx -> pdf (LibreOffice) -> jpg (PyMuPDF)
    tests/               # conftest, make_fixtures, test_api, test_ai, test_generator
  frontend/
    proxy.conf.json
    src/app/
      app.ts/html/css            # shell, nav, status pill
      core/models.ts, api.service.ts
      pages/styles/              # upload + style cards
      pages/create/              # style picker, lesson info, per-page rows, result
```

## 5. API
| Method | Path | Purpose |
|---|---|---|
| GET | /api/health | `ai_enabled`, `model`, `previews_enabled` |
| GET/POST | /api/styles | list / upload .pptx (multipart `file`, optional `name`) |
| PATCH/DELETE | /api/styles/{id} | rename / remove |
| POST/DELETE | /api/images, /api/images/{id} | upload / remove a picture (normalised to PNG/JPG, max 2000px) |
| POST | /api/generate | body: `style_id, title, topic, instructions, slides[{page, details, image_id}]` |
| GET | /api/generations, /api/generations/{id} | history / one result (polled until previews are ready) |
| GET | /api/generations/{id}/download | the .pptx |
Static: `/files/previews/...`, `/files/images/...`. Previews render in a background task (`preview_status`: pending, ready, unavailable, failed).

## 6. Important implementation details
- **Exemplar fallbacks:** title -> section -> content -> image; content -> image -> title -> section; image -> content -> title -> section. Least-used sample is chosen so repeated slide types vary. A warning is returned when a requested type isn't in the style.
- **Decoration vs content images:** pictures covering 85% or more of the slide (backgrounds) and images repeated on 2+ slides (logos, banners) are kept as style. Only other large pictures (over 10% of the slide) count as content images.
- **Pages with an image** are forced to kind `image`. If the sample has no picture, the body is narrowed to about 54% width and the picture is placed beside it (fit inside the box, aspect ratio kept). If the sample has a picture, the largest one is replaced in place.
- **Text:** keeps the first/longest paragraph's formatting, preserves literal bullets typed as characters, adds paragraph spacing for plain text boxes, shrinks font to fit (title min 24pt, body min 14pt, estimated not measured) and warns if it still can't fit.
- **Stale content:** large extra text boxes on a sample slide are removed so sample text can't leak. Slides containing tables/charts are marked `complex` and avoided.
- **PowerPoint "sections"** extension is stripped after deleting the samples (otherwise PowerPoint offers to repair the file).
- **Layout-only decks** (no sample slides) fall back to layouts and placeholders.
- **Angular:** zoneless, so async state uses signals. The create form draft is saved in localStorage.
- **AI model** is set by `CLAUDE_MODEL` in `.env` (default `claude-sonnet-5-5`). Forced tool `submit_slides`; pages the model skips fall back to the teacher's raw notes; bullets are capped to what the style can hold.

## 7. Status
**Verified**
- 8 automated tests passing from a clean unzip (API flow, Claude path against a faked response, generator edge cases: background photo + logo, layout-only deck, single-slide deck, overflow shrink and warning, PowerPoint sections).
- Full browser run (Playwright) in demo mode: upload styles, thumbnails, select style, per-page notes, image attach, generate, previews, download, duplicate-page validation, draft restore after reload. No console errors.
- Output files pass the pptx validator and render correctly in LibreOffice in the teacher's style.
- Frontend builds cleanly.

**Not verified**
- A live Claude call with a real API key (only tested with a fake response).
- Opening generated files in real Microsoft PowerPoint.
- Tests were run on fixture decks I built, not on many real teacher decks.

## 8. Known limits / not built
No login (everything shared), no regenerate-single-slide, one picture per page, tables/charts/grouped-shape text are not refilled, text fitting is an estimate, no history page in the UI (the API has it), local storage only.

## 9. Suggested next steps
1. Run with a real API key and 2-3 real teacher decks; open results in PowerPoint; log every failure.
2. Regenerate or edit a single slide; reorder, add and delete slides on the result page.
3. History page for past decks (the API already returns the last 20).
4. Multiple images per page; table support.
5. Authentication and per-teacher styles; then S3 + Postgres and hosting.
6. Optional: let the teacher tune slide size/density, and a "style check" screen showing which sample slide was used for each page.

## 10. Run it
See `SETUP.md` inside the zip. Short version:
```bash
# terminal 1
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env   # add ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
# terminal 2
cd frontend && npm install && npm start                   # http://localhost:4200
```
Top-right pill: "Claude connected", "Demo mode" (no key) or "Backend offline".
Tests: `cd backend && pip install pytest && python tests/make_fixtures.py && pytest -q`

## 11. Gotchas found while building
- `ng new` with the very latest Angular CLI needed a newer Node than 22.22.2; Angular 21 CLI worked. `npm install` once failed with an "edgesOut" error; `--legacy-peer-deps` fixed it.
- Bare `pytest` needs `pytest.ini` (`pythonpath = .`), already included.
- LibreOffice must run one conversion at a time (a lock is used) with its own profile directory.
- python-pptx can't write WebP, so images are converted on upload.
