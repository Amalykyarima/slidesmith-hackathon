# Hosting SlideSmith on Render (free, no card)

One Docker service serves the API and the Angular app at one address, with HTTPS.

## What the free plan means
- **Sleeps after 15 minutes** without visits; the next visit takes about a minute to wake it.
- **The disk is wiped** on every sleep, restart or deploy: uploaded style decks, pictures and
  generated decks disappear. Teachers re-upload their style deck after a sleep, and should
  download each deck when it's built.
- **750 free hours a month** per workspace (enough for one service running all month).
- **512 MB memory.** SlideSmith peaks around 350 MB because previews only cover the first
  12 slides of a deck (`PREVIEW_MAX_SLIDES`) and thumbnails are made in a separate process.

## One-time setup (about 10 minutes)
1. Go to **render.com**, choose **Get Started**, and sign up **with GitHub**.
2. **New → Blueprint**, pick the `slidesmith` repository, and click **Connect**. Render reads
   `render.yaml` from the repo.
3. Fill in the two secrets it asks for:
   - `ANTHROPIC_API_KEY`: your key from platform.claude.com (leave empty for demo mode).
   - `ACCESS_CODES`: one code per teacher, for example `Mrs Khan:maple-42, Mr Lee:river-7`.
     Pick codes that are hard to guess; each teacher only sees her own decks.
4. Click **Apply**. The first build takes 5-10 minutes (it installs LibreOffice).
5. Open the address Render shows (`https://slidesmith-xxxx.onrender.com`), sign in with a code,
   and run a lesson end to end.

Every merge to `main` deploys automatically.

## Settings (Render → the service → Environment)
| Setting | What it does | Default in render.yaml |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Turns on AI writing; empty = demo mode | (you set it) |
| `ACCESS_CODES` | `Name:code` pairs, comma-separated; empty = no sign-in (don't do that online) | (you set it) |
| `SECRET_KEY` | Signs the sign-in cookie | generated |
| `CLAUDE_MODEL` | Model for AI writing | `claude-sonnet-5-5` |
| `PREVIEW_MAX_SLIDES` | Slides per deck that get thumbnails | `12` |
| `AI_DAILY_LIMIT` | AI generations per teacher per day ("exact text" builds don't count) | `20` |

## If something goes wrong
- **Build fails:** Render → the service → **Logs**; paste the failing lines into Claude Code.
- **"Please sign in" loops:** check `ACCESS_CODES` is set and the code matches exactly.
- **Service restarted on its own / out of memory:** lower `PREVIEW_MAX_SLIDES` to 8.
- **Need files to survive sleeps:** that needs a paid instance with a disk, or the planned move
  to S3-style storage and Postgres.
