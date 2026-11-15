# Imperial AI Hack 2026: SlideSmith

Track: **Reply Challenge: AI on Campus** (Teaching, Learning, Assessment) · Bounties: none · Figma: No · Adaption: No

## Devpost write-up (paste into the form)

**Tagline:** An AI learning buddy that helps pupils with SEN work through their day independently, set up by their teacher in minutes.

### Inspiration
I'm a teaching assistant. Every lesson I see pupils with special educational needs (SEN) waiting for an adult
to explain, again, what to do next, because a class has one teacher and a TA can't sit with every pupil. In
England 1.32 million pupils are on SEN support without an EHC plan, and fewer than half of new EHC plans are
issued within the 20-week legal limit (46.1% in 2025). Most of these pupils get by on whatever help is free in
the moment. We wanted to give each of them something that helps them get started and keep going on their own.

### What it does
**For the pupil: "My day".** A pupil opens their laptop and picks the avatar they like (Mei, Jenny or Kenji).
It says hello, tells them what they'll learn in each period, and shows a visual breakdown: numbered steps with
symbols they can tick off, and key words with simple meanings. It listens. When they're stuck it gives a hint
or a smaller next step, not the answer. It shows a video only if the teacher added one, and it calls the
teacher when the pupil still needs a grown-up.

**For the teacher or TA.** On each pupil's page they set the day's periods in a few minutes: type what the
pupil will learn and the tasks, or upload the period's slides or worksheet. The AI turns each period into
the visual step-by-step breakdown. Help requests appear on the teacher's screen. The teacher can also:
- adapt any lesson or worksheet for a pupil's specific need (autism, speech and language, dyslexia...),
  grounded in the school's own provision map and the SEND Code of Practice, with sources;
- talk to a staff assistant avatar ("What's worked for AB?", "Adapt tomorrow's fractions lesson for AB",
  or a one-minute debrief after the lesson that becomes an assess-plan-do-review record to approve).

### Safe for children by design
- The pupil's avatar only talks about the day the teacher set. No web search, no videos the teacher didn't
  add, no personal questions.
- Anything that sounds like a pupil may be unsafe goes straight to the teacher's screen; it's caught by a rule
  in code, not left to the model.
- Pupils are stored by code or initials only; names, emails and phone numbers are refused or removed before
  anything reaches the AI.
- Everything for staff is a draft until a named member of staff approves it.

### How we built it
- **Frontend:** Angular 21 (standalone components, signals, zoneless).
- **Backend:** FastAPI with SQLite for session state (pupils, day plans, help requests, records).
- **AI:** Claude through strict tool calls, so every answer is validated JSON in fixed fields, never loose prose.
- **Live avatars:** Synthesia interactive avatars on LiveKit, with Cartesia speech and Claude as the brain.
  Each avatar is a LiveKit agent with tools (show the next lesson, show the teacher's video, call the
  teacher; or for staff: look up records, adapt a lesson, log a debrief), switching modes from what's said.
- **Visual supports:** symbols from OpenMoji, matched deterministically, so the same word always gets the same
  picture (consistency matters to autistic pupils).
- **RAG:** the SEND Code of Practice (Open Government Licence) plus the school's documents, BM25 retrieval,
  inline citations.
- **Tests:** 111 backend tests. Hosted on Render.

### Challenges
Making a pupil-facing AI safe: we kept it grounded in the teacher's plan, gave it hints-not-answers rules,
and put the safety checks that matter in code rather than in a prompt.

### Accomplishments
A teacher types three lines per lesson, and in about 7 seconds a pupil has a picture-supported plan for the
whole day and a friendly face to talk them through it.

### What's next
A pilot with a primary school's SEN team; teachers setting the day by voice; and further education colleges,
where 100,800 young people with EHC plans now study.

### Built with
angular, typescript, python, fastapi, claude, anthropic, synthesia, livekit, cartesia, sqlite, openmoji, render

---

## 2-minute video (organisers' structure)

| Time | Screen | Say |
|---|---|---|
| **0:00-0:15** The problem | Pupils page, then Y4-AB | "Pupils with special educational needs often wait for an adult to explain what to do next. SlideSmith gives every one of them a learning buddy, set up by their teacher." |
| **0:15-0:35** Teacher sets the day | Y4-AB → Today's lessons → edit a period → Save and make visual steps | "The teacher types what AB is learning in each period, or uploads the slides. In seconds each lesson becomes steps with pictures." |
| **0:35-1:20** Pupil's real run | Open My day → pick Mei → Let's start. Let the avatar greet and explain period 1. Say "I'm stuck on step 2", then "Can I watch the video?" | (Let the avatar talk. Keep your own lines short.) |
| **1:20-1:30** Teacher sees it | Back to Y4-AB → Help requests → Refresh → "On my way" | "And the teacher knows straight away." |
| **1:30-1:50** How it's built | README architecture, or the Codespaces terminal | "Claude with strict tool calls, Synthesia avatars on LiveKit, pictures from OpenMoji. The avatar only talks about the teacher's plan, gives hints not answers, and safety checks run in code." |
| **1:50-2:00** What's new and how often it works | Back to My day | "New: a pupil-facing AI that's grounded, safe and built for SEN. It's worked on every run we did today. SlideSmith." |

Before recording: wake the Render app, click **Load demo school**, start the avatar worker in Codespaces, and
do one practice run. Upload to YouTube as **Unlisted**.

## Sources for the numbers
- 46.1% of new EHC plans within 20 weeks in 2025; 100,800 young people with EHC plans in further education
  (January 2026): DfE, *Education, health and care plans*, 2026.
- 1,319,780 pupils on SEN support (2025/26): DfE, *Special educational needs in England*, 2025/26.
