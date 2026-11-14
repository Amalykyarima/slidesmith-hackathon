# SlideSmith: an AI teaching team for every classroom

**Imperial AI Hack 2026 · Reply Challenge: AI on Campus (Teaching track)**

Teachers and lecturers spend hours every week making slides, and still more adapting them for pupils
with special educational needs (SEN). SlideSmith gives them a team of AI agents that writes, adapts and
checks a lesson, a teacher who stays in charge of every decision, and a deck that comes back **in the
teacher's own PowerPoint style**. It works for **primary, secondary and university**.

It started as a real tool: a secondary-school teacher asked her teaching assistant (me) to automate her
daily slides, and the teachers there like it. This hackathon version adds the agent team, SEN visual
supports and a live avatar.

## What it does

| | |
|---|---|
| **Agent team, live** | Orchestrator → Guardrails → Planner → SEN Adapter → Reviewer → *you* → Builder. Every step streams to the screen as it happens (server-sent events). |
| **Mode-switching** | The Orchestrator picks modes per request: whole lesson or polish notes; Primary / Secondary / University (reading level, slide density, review strictness); SEN scaffolding on automatically for primary or when notes mention SEN, ADHD, autism, dyslexia… |
| **Guardrail pipeline** | In code, before the AI: names, emails, phones, pupil numbers and postcodes are removed; "ignore previous instructions" is neutralised. After the AI: reading level (Flesch-Kincaid), density and personal data are checked again. A second model reviews accuracy, age fit, safeguarding and inclusion. |
| **Human-in-the-loop escalation** | Anything flagged stops the build and goes to the teacher. She edits or accepts each point. Personal-data blocks can't be waved through. Nothing worrying? The deck builds straight away. |
| **SEN visual supports** | Now/Next boards, visual timetables, step-by-step task cards and key-word cards with consistent open symbols (OpenMoji). Editable, swappable symbols, coloured backgrounds for dyslexia, large text, print to PDF. Made from the lesson, or on their own in seconds for a TA. |
| **Live avatar (Synthesia + LiveKit)** | Talk to it to **build a lesson by voice**, then let it **present the deck**: it moves the slides, answers pupils' questions from the deck only, quizzes the class, and sends anything else (and any safeguarding concern, caught in code) to the teacher's inbox. Live captions on both sides. |
| **Session state** | Every run keeps its state and event log, so the teacher can leave, come back, review and approve. |
| **Her style, always** | The AI writes text only. Style comes from cloning the teacher's own sample slides (python-pptx): fonts, colours and layouts are hers, never generated. |

## Architecture

```
Angular 21 (signals, zoneless) ──► FastAPI ──► agents.py  Orchestrator, SEN Adapter, Reviewer (Claude, strict tool calls)
        │  SSE: /api/runs/{id}/events          ├─► ai.py      Planner (Claude)
        │                                      ├─► guardrails.py  rule-based checks (no model)
        │                                      ├─► generator.py   clones her slides, fills text (python-pptx)
        │                                      └─► pictos.py      OpenMoji symbols, deterministic matching
        └─► livekit-client ◄──► LiveKit Cloud ◄──► avatar/agent.py  Synthesia avatar · Cartesia STT/TTS · Claude
```

## Run it

Backend and frontend as below (no API key = demo mode, the whole flow works offline). The live avatar is
optional: see [avatar/README.md](avatar/README.md). Write-up and video script: [docs/HACKATHON.md](docs/HACKATHON.md).

---

## The original SlideSmith

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

## Hosting
`Dockerfile` + `render.yaml` deploy SlideSmith to Render's free plan as one service with
access-code sign-in. Step by step: [docs/HOSTING.md](docs/HOSTING.md). Every tool it is built with: [docs/TECH-STACK.md](docs/TECH-STACK.md). Locally nothing changes: without
`ACCESS_CODES` there is no sign-in.
