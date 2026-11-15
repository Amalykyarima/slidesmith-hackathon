# Imperial AI Hack 2026: SlideSmith, an AI copilot for SEN support

Reply Challenge: **AI on Campus** · Teaching, Learning and Assessment

## Devpost write-up (paste into the form)

### Inspiration
I work as a teaching assistant in a secondary school. I watch teachers and the SENCO spend evenings adapting
worksheets, writing up support and chasing reviews, while pupils with special educational needs wait. In
England, 1.32 million pupils are on SEN support without an EHC plan, and fewer than half of new EHC plans are
issued within the 20-week legal limit (46.1% in 2025). The help a pupil gets in class this week matters more than
paperwork, and good records of that help are also the evidence a pupil needs if they later need an EHC plan.

### What it does
SlideSmith is an AI copilot for teachers, teaching assistants and SENCOs.

- **Adapt classwork.** Upload a lesson or worksheet and choose a pupil or a need (autism, speech and language,
  moderate learning difficulty, dyslexia, ADHD). You get a printable version with the same learning objective:
  one-step instructions, scaffolds, small steps, a word bank, an explanation of every change, and the sources.
  One click makes visual supports with symbols (Now/Next board, step cards, key words).
- **Assess, plan, do, review.** A teacher logs what they tried in a few lines. The AI turns it into a structured
  record with SMART outcomes, provision, who and how often, success criteria and what's still missing. Staff
  edit and approve it, and its review date feeds the SENCO's dashboard.
- **SENCO overview.** Everyone on the register, reviews overdue or due soon, provision in use, records waiting
  for approval, and a light pastoral flag when attendance falls below 90% or is dropping.
- **Drafts for staff to sign.** A SEN support plan, the school's contribution to an EHC needs assessment, and a
  plain-English update for parents, built only from approved records and the school's own documents. Gaps
  are marked "[to add: ...]" and block signing; each draft comes with a list of what to check.

It does not diagnose, write EHC plans, replace an educational psychologist, or talk to pupils.

### How we built it
- **Frontend:** Angular 21 (standalone components, signals, zoneless).
- **Backend:** FastAPI with SQLite session state: pupils, APDR records, drafts, attendance, school documents.
- **AI:** Claude through strict tool calls, so every answer is validated JSON in fixed fields (assess, plan,
  outcomes...) rather than loose prose. Demo mode runs without a key.
- **RAG:** the SEND Code of Practice (summarised, Open Government Licence) plus the school's uploaded documents,
  retrieved with BM25. Every answer cites passages inline ([C3], [S2]) and the teacher can open each source.
- **Guardrails, in code:** pupils are stored by code or initials only; full names, emails, phone numbers, pupil
  numbers and dates of birth are refused or removed before anything reaches the AI; prompt-injection text in
  uploaded documents is neutralised.
- **Human in the loop:** records count only once a named member of staff approves them; drafts can't be signed
  until every gap is filled; signed documents are locked.
- **Agent team** (from the original SlideSmith): Orchestrator, Planner, SEN Adapter and Reviewer agents with a
  live feed and teacher approval, plus slides in the teacher's own style and a live Synthesia avatar on LiveKit.
- **Tests:** 110 backend tests.

### Challenges
Making AI useful without letting it overreach: the line between "drafts the evidence" and "makes the decision"
had to be built into the product (approval, sign-off, [to add] gaps, no diagnosis), not just into a prompt.

### Accomplishments
A teacher's three-line note becomes a review-ready record with a baseline and SMART outcomes in about 25
seconds. An adapted worksheet keeps the same objective, uses the school's own provision, and explains why.

### What's next
A pilot with a primary school and its SENCO; a UK-hosted model deployment; MIS integration for attendance
(Arbor, SIMS); and further education colleges, where 100,800 young people with EHC plans now study.

### Built with
angular, typescript, python, fastapi, claude, anthropic, sqlite, rag, bm25, python-pptx, livekit, synthesia

---

## 2-minute video script

| Time | Screen | Say |
|---|---|---|
| 0:00-0:12 | SEN overview (demo school loaded) | "Fewer than half of EHC plans arrive on time. Meanwhile teachers and SENCOs are buried in adapting work and paperwork. SlideSmith is an AI copilot that gets pupils with SEN help now." |
| 0:12-0:25 | Point at the tiles and the Y4-AB row | "The SENCO sees everyone on SEN support: reviews overdue, provision in use, and an attendance flag. AB's review is overdue and his attendance is dropping." |
| 0:25-0:55 | Adapt classwork → pupil Y4-AB → example worksheet → Adapt it | "A teacher uploads tomorrow's fractions worksheet for AB. The same objective, but one-step instructions, a worked example using his love of trains, and a word bank. Every change is explained and cited, from the school's own provision map and the Code of Practice." |
| 0:55-1:05 | Make visual supports | "One click, and he has a Now/Next board and step cards." |
| 1:05-1:30 | Pupil page → example note → Turn into a record → Approve | "After the lesson, three lines on what worked. It becomes a proper assess-plan-do-review record with SMART outcomes and a baseline, and it tells me what's still missing. I approve it, and the review date updates." |
| 1:30-1:50 | Update for parents → show [to add] and the check list | "Drafts for parents, a support plan, or evidence for an EHC needs assessment. Gaps are marked, nothing is invented, and it can't be signed until a human fills them." |
| 1:50-2:00 | Back to the overview | "No diagnosis, no pupil chatbot, no names sent to the AI. Help now, and evidence that's ready when it's needed. SlideSmith." |

Recording tips: load the demo school, run each AI step once before recording so you know the timings (about
20-30 seconds each; the EHC contribution takes about a minute), then record and trim the waits.

---

## Before you demo: checklist

1. `backend/.env` has `ANTHROPIC_API_KEY`. Never commit it.
2. Open the app and click **Load demo school** on the SEN overview.
3. The demo school, provision map and pupils are fictional; pupils are codes only.

## Sources for the numbers
- 46.1% of new EHC plans issued within 20 weeks in 2025; 100,800 young people with EHC plans in further
  education (January 2026): DfE, *Education, health and care plans*, 2026.
- 1,319,780 pupils on SEN support (2025/26): DfE, *Special educational needs in England*, 2025/26.
