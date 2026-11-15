# SlideSmith Live: the avatar worker

A Synthesia interactive avatar on LiveKit that **builds lessons by voice** and **presents them to the class**.
It is a separate process from the web app: it connects out to LiveKit Cloud and calls SlideSmith's API.

```
Browser (/live) ──► POST /api/avatar/token ──► LiveKit room, dispatches "slidesmith-avatar"
                                                    │
          speech ◄── Synthesia avatar (video) ◄── agent.py: STT ─► Claude (tools) ─► TTS
                                                    │
                       SlideSmith API (/api/runs, /api/generations) ◄── tools act for the teacher
```

## Modes (switched mid-conversation)

| Mode | What happens | Tools |
|---|---|---|
| **Debrief** (default) | A teacher or TA talks for a minute after a lesson. The avatar asks the follow-ups a good record needs (pupil voice, parents, numbers, next step), reads back a summary, and creates a draft assess-plan-do-review record that staff approve on screen. Pupils by code only; safeguarding concerns are sent to the DSL, never into a record | `log_support`, `flag_for_safeguarding_lead` |
| Build | The teacher says what she needs. The avatar confirms, starts SlideSmith's agent team, narrates progress, and tells her when the Reviewer escalates something | `create_lesson`, `check_progress`, `present_lesson` (hands off to Present) |
| Present | The avatar teaches the deck slide by slide, moves the slides on screen and answers questions **from the deck only** | `show_slide`, `set_mode` (present / questions / quiz), `ask_teacher` |

Human-in-the-loop: questions the deck can't answer, and anything that sounds like a safeguarding concern,
appear in the teacher's inbox on screen. Safeguarding phrases are also caught **in code** from the pupil's
transcript, so escalation never depends on the model.

## Run it

Python 3.10–3.14. On an older Intel Mac, run it in GitHub Codespaces (the devcontainer installs it).

```bash
cd avatar
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in LiveKit, Synthesia, Anthropic keys and AVATAR_SECRET
python agent.py dev
```

The backend needs the same LiveKit keys and `AVATAR_SECRET` in `backend/.env`. Then open the app,
go to **Live avatar**, and click **Start**. Never use `python agent.py console`: it uses a mock room and
the avatar never appears.

If the web app is hosted (Render) and the worker runs elsewhere, set `SLIDESMITH_URL` to the hosted address.
