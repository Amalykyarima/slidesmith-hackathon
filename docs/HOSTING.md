# Hosting SlideSmith on Render (free, no card)

One Docker service serves the API and the Angular app at one address, with HTTPS.

## What the free plan means
- **Sleeps after 15 minutes** without visits; the next visit takes about a minute to wake it.
- **The disk is wiped** on every sleep, restart or deploy (unless you set up Supabase storage below): uploaded style decks, pictures and
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

## Keep teachers' work (free Supabase storage, no card)

Without this, the free server's disk is wiped on every sleep and deploy: teachers lose their
styles and decks. With it, SlideSmith saves everything to a private Supabase bucket every
15 seconds (and on shutdown) and brings it all back when the server wakes.

1. Sign up at https://supabase.com (free, no card) → **New project** (any name, a strong
   database password you can forget, region **London** or **Frankfurt**).
2. **Storage** → **New bucket** → name `slidesmith`, leave **Public bucket OFF** → Create.
3. **Project Settings → API**: copy the **Project URL** and the **service_role** (secret) key.
4. Render → the service → **Environment** → add `SUPABASE_URL` (the URL) and
   `SUPABASE_SERVICE_KEY` (the secret key) → **Save, rebuild and deploy**.
5. Check: open `https://<your-app>.onrender.com/api/health`. `"storage"` should say
   `"mode": "supabase"`, and after an upload `"files"` goes up.

The secret key can read and write everything in the project: keep it only in Render's
environment, never in the code or chat. Free plan limits: 1 GB in total and 50 MB per file
(style decks are capped at 40 MB). A free project pauses after a week with no requests;
SlideSmith sends a tiny request once a day while it runs, and you can un-pause it from the
Supabase dashboard if the school was closed for a holiday.

## Keep it awake during school hours (free, recommended)

The free server sleeps after 15 minutes without visitors; the next visit waits about a minute while
it wakes, and the disk is wiped. A free pinger visiting every 10 minutes during the school day stops
both. Render gives 750 free hours a month; weekdays 06:00–18:00 use about 270.

1. Sign up at https://cron-job.org (free, no card).
2. **Create cronjob** → URL `https://<your-app>.onrender.com/api/health` (this page needs no sign-in).
3. Schedule: **Custom** → every 10 minutes, hours 6–18, Monday–Friday, time zone Europe/London.
4. Save. In Render → **Logs** you will see a `GET /api/health` every 10 minutes.

GitHub Actions can ping too, but on a private repo each ping uses a minute of the 2,000 free Actions
minutes a month, so an outside pinger is the better fit.

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
