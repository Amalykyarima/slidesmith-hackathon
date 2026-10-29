# SlideSmith: step-by-step setup

Every step below was run from a clean unzip before writing this.

## 0. Install once
- **Python 3.10+** (check: `python --version`)
- **Node.js 20.19+ or 22.12+** (check: `node -v`)
- **LibreOffice** (optional, only for slide thumbnails): https://www.libreoffice.org/download
- An **Anthropic API key** (optional for testing, needed for real AI): https://console.anthropic.com

## 1. Unzip
Unzip `slidesmith.zip`. You get `backend/` and `frontend/`.

## 2. Backend (terminal 1)
```bash
cd slidesmith/backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```
Open `.env` and set `ANTHROPIC_API_KEY=sk-ant-...`. If you use LibreOffice and previews don't appear, also set `SOFFICE_BIN` to its path.

Start it:
```bash
uvicorn app.main:app --reload --port 8000
```
Check: open http://localhost:8000/api/health. You should see `"ai_enabled": true` (false means the key wasn't read) and `"previews_enabled"` true if LibreOffice was found.

## 3. Frontend (terminal 2)
```bash
cd slidesmith/frontend
npm install                        # if it errors with "edgesOut": npm install --legacy-peer-deps
npm start
```
Open http://localhost:4200. The top-right pill should say **Claude connected**. "Demo mode" means no key; "Backend offline" means step 2 isn't running.

## 4. Run the tests (optional, 20 seconds)
In terminal 1 (venv active), stop the server or open another terminal:
```bash
cd slidesmith/backend
pip install pytest
python tests/make_fixtures.py
pytest -q                          # expect: 8 passed
```

## 5. First real run
1. **Styles page:** drop in 2-3 real decks from the teacher (.pptx). Each should have a title slide, a bullet slide and a picture slide.
2. Click **Use this style**.
3. **Create page:** add a title, then notes for pages 1-4. Attach a picture on one page.
4. **Generate**, check previews, **Download .pptx**, open it in PowerPoint.

## 6. Demo-day checklist
- Do the whole flow once on the same laptop you'll present from.
- Keep a backup: a generated .pptx saved on the desktop.
- No wifi? Remove the API key from `.env` and restart the backend to use Demo mode.
- If a style looks wrong, open its sample deck: the likely cause is a missing slide type or a table/chart on the sample slides.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `Backend offline` pill | Backend not running or not on port 8000 |
| `ModuleNotFoundError: app` | Run commands from inside `backend/` |
| "The API key was rejected" | Re-copy the key into `.env`, restart uvicorn |
| AI error mentioning the model | Change `CLAUDE_MODEL` in `.env` to a model your account can use |
| No thumbnails | Install LibreOffice, set `SOFFICE_BIN`, restart backend |
| Text overflows a slide | Shorten the notes; the app warns when it can't fit text |
| Port 4200 or 8000 busy | Stop the other process, or `ng serve --port 4300` / `--port 8001` (update `proxy.conf.json`) |

## Production build (later)
`cd frontend && npm run build` outputs static files to `dist/`. Host them behind the same domain as the API, or point the proxy paths at your API URL.
