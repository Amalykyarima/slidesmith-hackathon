# Imperial AI Hack 2026: SlideSmith

Reply Challenge: **AI on Campus** · Teaching (with Learning and Assessment support)

## Devpost write-up (paste into the form)

### The problem
Lecturers, teachers and teaching assistants spend hours a week turning notes into slides, and then more
time adapting them for students who need it: neurodivergent students, students with dyslexia, students
with lower reading ages or English as an additional language. At university that adaptation is often
a "reasonable adjustment" that rarely gets done, because nobody has the time. Generic AI tools make it
worse in their own way: they produce slides in someone else's style, invent facts, and give a lecturer no
say before the content reaches students.

### What SlideSmith does
SlideSmith is an AI teaching team for any classroom: primary, secondary or university.

1. **The lecturer uploads her own PowerPoint decks** as styles and says what today's session needs, or
   simply talks to the live avatar.
2. **A team of agents works on it, live on screen.** The Orchestrator chooses the modes (level, whole
   lesson or polish notes, SEN scaffolding, review strictness). Guardrails strip personal data before
   anything reaches the AI. The Planner writes the slides. The SEN Adapter simplifies wording, picks
   symbols and makes step cards. The Reviewer, a second model, checks accuracy, age fit, safeguarding
   and inclusion.
3. **Anything worrying is escalated to the human.** The build stops and the lecturer edits or accepts
   each flag. Personal data can't be waved through. If nothing is flagged, the deck builds straight away.
4. **The deck comes back in her own style**, because SlideSmith clones her own slides and the AI only
   writes the text. She also gets a printable pack of visual supports: Now/Next board, visual
   timetable, step-by-step task cards and key-word cards with symbols.
5. **A live Synthesia avatar** can take the whole request by voice, then present the finished deck,
   answer students' questions from the deck only, and pass anything else (including safeguarding
   concerns, caught in code) to the lecturer's inbox, with live captions.

### How we built it
- **Frontend:** Angular 21 (standalone components, signals, zoneless), server-sent events for the live
  agent feed, livekit-client for the avatar room and live captions.
- **Backend:** FastAPI, SQLite session state (every run keeps its state and event log), python-pptx to
  clone the teacher's slides.
- **Agents:** Claude through strict tool calls, so every agent returns validated JSON and none of them
  touches PowerPoint. Orchestrator, Planner, SEN Adapter and Reviewer, with deterministic stand-ins so the
  whole flow runs offline in demo mode.
- **Guardrail pipeline:** rule-based input checks (personal data, prompt injection), rule-based output
  checks (Flesch-Kincaid reading level per level, density, personal data) plus the model reviewer;
  sensitive topics at primary and secondary always escalate by rule.
- **Symbols:** OpenMoji (CC BY-SA 4.0), matched deterministically from the SEN Adapter's words, so the
  same word gets the same symbol every time (consistency matters to autistic students).
- **Live avatar:** LiveKit Agents + the Synthesia plugin, Cartesia speech through LiveKit, Claude as the
  brain. Two agents in one session: a Builder that calls SlideSmith's API and a Presenter grounded only in
  the deck, with a handoff between them.
- **Tests:** 107 backend tests, including the agent pipeline, escalation, approval and the avatar's
  room tokens.

### Challenges
Keeping the teacher's style exact while letting AI write; making escalation trustworthy (rules that can't
be talked out of a decision, plus a model for judgement); and grounding a talking avatar so it never
invents facts in front of a class.

### What we're proud of
It is a real tool first: it began when a teacher at the school where I work as a teaching assistant
asked for her slides to be automated, and the teachers there like it. The hackathon version turns it
into an agent team that any lecturer or TA can trust, because a human approves anything doubtful.

### What's next
A pilot with a university disability and inclusion service; ARASAAC symbol support; per-student
adaptation profiles; and an LMS export (Moodle, Blackboard).

### Built with
angular, typescript, python, fastapi, claude, anthropic, livekit, synthesia, cartesia, python-pptx,
sqlite, openmoji, docker, render

---

## 2-minute video script

| Time | Screen | Say |
|---|---|---|
| 0:00-0:12 | Title card, then the Create page | "Lecturers spend hours on slides, and adapting them for students with additional needs often never happens. SlideSmith is an AI teaching team that does both, in your own style." |
| 0:12-0:25 | Pick a style; click Primary / Secondary / University | "One product for every level. I pick my own PowerPoint style and who it's for. That changes reading level, density and how strict the review is." |
| 0:25-0:50 | Generate; the agent rail lights up; the feed scrolls | "A team of agents works live. The Orchestrator picks modes, Guardrails remove personal data before anything reaches the AI, the Planner writes, the SEN Adapter simplifies and adds symbols, and a second model reviews it." |
| 0:50-1:10 | "Your AI team needs you"; edit the flagged slide; Approve | "Anything worrying comes to me. Here it flagged a sensitive topic. I edit it and approve. Personal data can't be waved through at all." |
| 1:10-1:25 | Result in her style; scroll to the visual supports; change background; Print | "The deck comes back in my own style, with a printable pack for students who need it: Now and Next, a visual timetable, step cards and key words with consistent symbols." |
| 1:25-1:50 | Live avatar: say "A first-year lecture on supply and demand, 8 slides"; agents run; "Present it" | "Or I just talk to it. The avatar runs the same team, then presents the deck, answers questions from the slides only, and sends anything else to my inbox." |
| 1:50-2:00 | Inbox with a question; logo | "AI that does the work, and a human who stays in charge. SlideSmith." |

Recording tips: record the avatar part first (it needs the live keys), keep the browser at 1280 px wide,
and use a lesson you have already run once so the agents finish quickly on camera.

---

## Before you demo: checklist

1. `backend/.env`: `ANTHROPIC_API_KEY`, the three `LIVEKIT_*` values from your pass page, and a long random
   `AVATAR_SECRET`.
2. `avatar/.env`: the same LiveKit values and `AVATAR_SECRET`, plus `SYNTHESIA_API_KEY` and
   `ANTHROPIC_API_KEY`. Run `python agent.py dev` (Codespaces if your Mac can't).
3. Never commit either `.env` file (both are git-ignored). The LiveKit keys are for this hackathon only.
4. Upload one university-style deck and one school deck on the Styles page before recording.
