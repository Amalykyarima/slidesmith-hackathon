# Imperial AI Hack 2026: SlideSmith, an AI copilot for SEN support

Reply Challenge: **AI on Campus** · Teaching, Learning and Assessment

## Devpost write-up (paste into the form)

### Inspiration
I work as a teaching assistant in a secondary school. Every day I see pupils with special educational needs
handed the same worksheet as everyone else, because adapting it takes time teachers don't have. In England,
1.32 million pupils are on SEN support without an EHC plan, and fewer than half of new EHC plans are issued
within the 20-week legal limit (46.1% in 2025). Help in the lesson, this week, is what changes a pupil's
learning, and the same cycle applies in colleges, where 100,800 young people with EHC plans now study.

### What it does
SlideSmith is an AI copilot for teachers, teaching assistants and SENCOs, built around teaching, learning and
assessment.

- **Teaching: adapt classwork.** Upload a lesson or worksheet and choose a pupil or a need (autism, speech and
  language, moderate learning difficulty, dyslexia, ADHD). You get a printable version with the same learning
  objective: one-step instructions, scaffolds, small steps, a word bank, an explanation of every change, and
  the sources it used.
- **Learning: visual supports.** One click turns the adapted work into a Now/Next board, step-by-step task
  cards and key-word cards with consistent symbols, so the pupil can follow and do the work.
- **Assessment: assess, plan, do, review.** After the lesson, the teacher logs what they tried in a few lines.
  The AI turns it into a structured record: what was observed, SMART outcomes with a baseline, the support,
  who and how often, success criteria, and what's still missing. Staff edit and approve it, and it sets the
  next review. Each cycle builds on the last.

- **Sam, the voice assistant, is the front door.** Teachers and TAs open the app and talk to a live avatar:
  *"What's worked for AB?"* (it answers from approved records only), *"Adapt tomorrow's fractions lesson
  for AB"* (the adapted worksheet appears on screen), and after the lesson *"Debrief for AB…"* (it asks the
  follow-ups a good record needs and drafts the record for approval). The whole assess-plan-do-review cycle,
  by voice, switching between modes from what the teacher says. TAs see the most and write the least; now
  they can just talk.

It does not diagnose, write EHC plans, replace an educational psychologist, or talk to pupils.

### How we built it
- **Frontend:** Angular 21 (standalone components, signals, zoneless).
- **Backend:** FastAPI with SQLite session state: pupils, assess-plan-do-review records, school documents.
- **AI:** Claude through strict tool calls, so every answer is validated JSON in fixed fields (assess,
  outcomes, provision...) rather than loose prose. Demo mode runs without a key.
- **RAG:** the SEND Code of Practice (summarised, Open Government Licence) plus the school's uploaded documents,
  such as its provision map, retrieved with BM25. Every answer cites passages inline ([C3], [S2]) and staff can
  open each source.
- **Guardrails, in code:** pupils are stored by code or initials only; full names, emails, phone numbers, pupil
  numbers and dates of birth are refused or removed before anything reaches the AI; prompt-injection text in
  uploaded documents is neutralised.
- **Human in the loop:** every output is a draft; a record counts only once a named member of staff approves it.
- **Live debrief avatar:** a Synthesia avatar on LiveKit (Cartesia speech, Claude as the brain) with tools that
  look up pupils by code and create the draft record through the app's API. Safeguarding phrases are caught in
  code and sent to the screen for the designated safeguarding lead, never into a record.
- **Also in the box** (from the original SlideSmith): an agent team (Orchestrator, Planner, SEN Adapter,
  Reviewer) that builds slides in the teacher's own PowerPoint style with a live feed and teacher approval,
  and a live Synthesia avatar on LiveKit.
- **Tests:** 110 backend tests.

### Challenges
Keeping AI useful without letting it overreach. The line between "suggests" and "decides" is built into the
product (staff approval, cited sources, no diagnosis), not just written in a prompt.

### Accomplishments
A teacher's three-line note becomes a review-ready record with a baseline and SMART outcomes in about 25
seconds. An adapted worksheet keeps the same objective, uses the school's own provision, builds on the pupil's
interests, and explains every change.

### What's next
A pilot with a primary school and its SENCO, a UK-hosted model deployment, and further education colleges.

### Built with
angular, typescript, python, fastapi, claude, anthropic, sqlite, rag, bm25, python-pptx, livekit, synthesia

---

## 2-minute video script

| Time | Screen | Say |
|---|---|---|
| 0:00-0:12 | Assistant page, Sam on screen | "Pupils with special educational needs often get the same worksheet as everyone else, because adapting it takes time teachers don't have. SlideSmith is an AI copilot for teaching, learning and assessment." |
| 0:12-0:45 | Adapt classwork → pupil Y4-AB → example worksheet → Adapt it | "Here's tomorrow's fractions worksheet, for AB, who is autistic. Same objective, but one-step instructions, a worked example using his love of trains, and a word bank. Every change is explained and cited, from the school's own provision map and the SEND Code of Practice." |
| 0:45-1:00 | Make visual supports | "One click, and he has a Now/Next board and step cards with symbols, so he can do the work on his own." |
| 1:00-1:35 | Y4-AB page → example note → Turn into a record → edit one outcome → Approve | "After the lesson, three lines on what worked. It becomes a proper assess-plan-do-review record: SMART outcomes with a baseline, success criteria, and what's still missing. I check it, approve it, and the next review is set." |
| 1:35-1:50 | Lesson debrief: say "Debrief for Y4-AB…", answer one follow-up, "log it"; Review and approve | "No time to type? The TA just talks to it for a minute after the lesson. It asks what's missing, and the record is waiting for approval. Every point is cited, so nothing is made up." |
| 1:50-2:00 | Pupils page | "No diagnosis, no pupil chatbot, no names sent to the AI. The right help in the lesson now, in schools and colleges. SlideSmith." |

Recording tips: load the demo school, run each AI step once before recording so you know the timings (about
20-30 seconds each), then record and trim the waits.

---

## Before you demo: checklist

1. `backend/.env` has `ANTHROPIC_API_KEY`. Never commit it.
2. Open the app, go to **Pupils** and click **Load demo school**.
3. The demo school, provision map and pupils are fictional; pupils are codes only.

## Sources for the numbers
- 46.1% of new EHC plans issued within 20 weeks in 2025; 100,800 young people with EHC plans in further
  education (January 2026): DfE, *Education, health and care plans*, 2026.
- 1,319,780 pupils on SEN support (2025/26): DfE, *Special educational needs in England*, 2025/26.
