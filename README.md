# SlideSmith (working name)

Teachers upload sample slide decks (their "styles"), then describe what goes on each page of today's lesson. SlideSmith builds a new .pptx in the same style.

**How it works:** each sample slide is analysed (title / content / image / section). For every requested page the best matching sample slide is *cloned* and its text and picture are replaced, so fonts, colours, backgrounds and positions carry over exactly. Claude only writes the text (structured JSON); it never touches PowerPoint files.

See **SETUP.md** for the full step-by-step guide. Short version:

## Run it

You need Python 3.10+ and Node 20+.

**Backend**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # add ANTHROPIC_API_KEY (optional, see below)
uvicorn app.main:app --reload --port 8000
```

**Frontend** (second terminal)
```bash
cd frontend
npm install            # if npm errors with "edgesOut", use: npm install --legacy-peer-deps
npm start              # http://localhost:4200 (proxies /api and /files to port 8000)
```

- **No API key?** The app runs in *Demo mode*: slides are built from the teacher's notes as typed. Good for checking the UI and style matching.
- **Previews** (slide thumbnails) need LibreOffice installed. Without it everything still works, only thumbnails are missing. Set `SOFFICE_BIN` in `.env` if it isn't found automatically.
- Model is set by `CLAUDE_MODEL` in `.env`.

## Tests
```bash
cd backend && pip install pytest && python tests/make_fixtures.py && pytest -q
```

## Demo script (5 minutes)
1. **Styles:** upload 2 real decks from the teacher. Point out the detected fonts, colours and slide types.
2. **Create:** pick a style, give a title, add 3-4 pages of rough notes, attach a picture to one page.
3. **Generate**, show the previews, download, open in PowerPoint.
4. Delete a style, upload another, generate again to show styles are swappable.

## Tips for good results
- Each style deck should contain a title slide, a bullet slide and a slide with a picture. Missing types fall back to the closest one and a warning is shown.
- Keep tables and charts out of sample slides (they are skipped as templates).

## Known limits / next steps
- No login: everything is shared. Add auth before real use.
- One picture per page; no regenerate-single-slide yet.
- Tables, charts and text inside grouped shapes are not refilled.
- Text fitting is estimated, not measured. Very long text is shrunk to 14pt, then flagged.
- Local disk + SQLite storage; move to S3 + Postgres for hosting.
- Not yet checked against many real teacher decks. Collect failures tomorrow.

## Develop in the cloud (no local install)
Click **Code → Codespaces → Create codespace on main** on GitHub. The container installs Python 3.12,
Node 22, LibreOffice and Claude Code. Then in its terminal: put your key in `backend/.env`, start the
backend (`cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000`) and,
in a second terminal, the frontend (`cd frontend && npm run start:cloud`). Run `claude` in a third.

## Slides you've already written
On the Create page, tick **Use my text exactly (no AI)**: each page's first line becomes the slide title and every
further line a bullet, built in your style with no AI call. **Import lesson file** loads a JSON lesson such as
`docs/examples/alcohol_lesson.json` (`{ "title", "slides": [{ "page", "title", "bullets", "role", "notes" }] }`).
`role` (e.g. `retrieval`, `turn_and_talk`, `we_do`, `you_do`) picks your matching routine slide; it is optional because
headings like "Turn and Talk" are recognised anyway. The API behind it is `POST /api/build`.
