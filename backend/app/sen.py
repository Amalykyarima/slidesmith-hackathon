"""SEN copilot for teaching, learning and assessment: adapt classwork for a pupil's needs, and run the
assess-plan-do-review cycle on what was tried.

Rules that hold everywhere in this module:
- Pupils are stored by code or initials only; full names, emails, phone numbers, UPNs and dates of birth
  are refused or removed before anything reaches the AI.
- Every AI output is grounded in retrieved passages (Code of Practice + the school's own documents) and
  cites them; the teacher sees the sources.
- Every AI output is a draft. A record only counts once a named member of staff approves it.
  Nothing here diagnoses or talks to pupils.
"""
from __future__ import annotations

import io
import re
import uuid
import zipfile
from datetime import date, timedelta

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import config, db, guardrails, kb, levels
from .agents import _friendly, call_tool
from .auth import owner

router = APIRouter(prefix="/api/sen")

NEED_AREAS = {
    "communication_interaction": "Communication and interaction",
    "cognition_learning": "Cognition and learning",
    "semh": "Social, emotional and mental health",
    "sensory_physical": "Sensory and/or physical",
}
NEEDS = [  # specific needs a teacher can adapt for, mapped to the Code's broad areas
    {"key": "autism", "label": "Autism", "area": "communication_interaction"},
    {"key": "slcn", "label": "Speech, language and communication", "area": "communication_interaction"},
    {"key": "mld", "label": "Moderate learning difficulty", "area": "cognition_learning"},
    {"key": "dyslexia", "label": "Dyslexia (specific learning difficulty)", "area": "cognition_learning"},
    {"key": "adhd", "label": "ADHD / attention", "area": "semh"},
    {"key": "semh", "label": "Social, emotional and mental health", "area": "semh"},
    {"key": "vi", "label": "Visual impairment", "area": "sensory_physical"},
    {"key": "hi", "label": "Hearing impairment", "area": "sensory_physical"},
    {"key": "eal", "label": "EAL (not SEN, but often adapted for)", "area": ""},
]
STATUSES = ["Monitoring", "SEN support", "EHC plan"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS pupils (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL DEFAULT '', code TEXT NOT NULL, year_group TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT 'primary', status TEXT NOT NULL DEFAULT 'SEN support', need_area TEXT NOT NULL DEFAULT '',
    needs TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '', strengths TEXT NOT NULL DEFAULT '',
    provision TEXT NOT NULL DEFAULT '[]', next_review TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(owner, code)
);
CREATE TABLE IF NOT EXISTS sen_adaptations (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL DEFAULT '', pupil_id TEXT, data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS apdr (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL DEFAULT '', pupil_id TEXT NOT NULL, note TEXT NOT NULL,
    record TEXT NOT NULL DEFAULT '{}', sources TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'draft',
    author TEXT NOT NULL DEFAULT '', approved_by TEXT NOT NULL DEFAULT '', review_date TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')), approved_at TEXT
);
"""


def init_db() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(kb.SCHEMA)
        conn.executescript(DAY_SCHEMA)


# --------------------------------------------------------------------------- guardrails
FULL_NAME = re.compile(r"^[A-Z][a-z]+(?:[- ][A-Z][a-z]+)+$")


def _clean_code(code: str) -> str:
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "Give the pupil a code or initials.")
    if len(code) > 16 or FULL_NAME.match(code) or guardrails.find_personal_data(code):
        raise HTTPException(400, "Use initials or a school code (for example \"Y4-AB\"), not a name or personal details.")
    return code


def _redact(text: str) -> str:
    text, _ = guardrails.redact(text or "")
    text, _ = guardrails.neutralise_injection(text)
    return text


# --------------------------------------------------------------------------- helpers
def _pupil(pid: str) -> dict:
    row = db.one("SELECT * FROM pupils WHERE id=? AND owner=?", (pid, owner()))
    if not row:
        raise HTTPException(404, "Pupil not found.")
    return _pupil_out(row)


def _pupil_out(row: dict) -> dict:
    p = dict(row)
    p["needs"] = db.loads(p["needs"], [])
    p["provision"] = db.loads(p["provision"], [])
    p["need_area_label"] = NEED_AREAS.get(p["need_area"], "Not yet identified")
    return p


def _needs_text(p: dict) -> str:
    labels = [n["label"] for n in NEEDS if n["key"] in p["needs"]]
    return ", ".join(labels) or p["need_area_label"]


def _pupil_brief(p: dict) -> str:
    return (f"Pupil {p['code']} ({p['year_group'] or 'year not given'}, {p['phase']}), status: {p['status']}.\n"
            f"Area of need: {p['need_area_label']}. Needs: {_needs_text(p)}.\n"
            f"Summary: {p['summary'] or '(none)'}\nStrengths: {p['strengths'] or '(none)'}\n"
            f"Current provision: {'; '.join(p['provision']) or '(none recorded)'}")


def _history(pid: str, limit: int = 6) -> str:
    rows = db.many("SELECT * FROM apdr WHERE pupil_id=? AND owner=? ORDER BY created_at DESC LIMIT ?", (pid, owner(), limit))
    out = []
    for r in rows:
        rec = db.loads(r["record"], {})
        out.append(f"- {r['created_at'][:10]} ({r['status']}): assess: {rec.get('assess', '')} | plan outcomes: "
                   f"{'; '.join(rec.get('plan', {}).get('outcomes', []))} | do: {rec.get('do', '')} | review: "
                   f"{'; '.join(rec.get('review', {}).get('success_criteria', []))}")
    return "\n".join(out) or "(no records yet)"


GROUNDING = """Ground everything in the passages provided. Cite them inline with their ids in square brackets, like [C3]
or [S2], wherever a point comes from them; prefer the school's own documents [S..] for what provision exists.
Never invent provision the school does not offer, never diagnose, never name a condition the teacher did not
give, and never include names or personal details. Everything you write is a draft for staff to check."""


def _ai(system: str, user: str, tool: dict, max_tokens: int = 6000) -> dict:
    try:
        return call_tool(system, user, tool, max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, _friendly(exc))


def _strict(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"name": name, "description": desc, "strict": True,
            "input_schema": {"type": "object", "properties": props, "required": required, "additionalProperties": False}}


STR = {"type": "string"}
STRS = {"type": "array", "items": {"type": "string"}}


# --------------------------------------------------------------------------- reference data
@router.get("/meta")
def meta():
    return {"need_areas": [{"key": k, "label": v} for k, v in NEED_AREAS.items()], "needs": NEEDS,
            "statuses": STATUSES, "ai": config.AI_ENABLED, "code_of_practice": kb.CREDIT}


# --------------------------------------------------------------------------- pupils
@router.get("/pupils")
def list_pupils():
    counts = {r["pupil_id"]: r for r in db.many(
        "SELECT pupil_id, COUNT(*) AS n, MAX(created_at) AS last FROM apdr WHERE owner=? GROUP BY pupil_id", (owner(),))}
    out = []
    for r in db.many("SELECT * FROM pupils WHERE owner=? ORDER BY code", (owner(),)):
        p = _pupil_out(r)
        c = counts.get(p["id"], {})
        p["records"] = c.get("n", 0)
        p["last_record"] = (c.get("last") or "")[:10] or None
        out.append(p)
    return out


@router.post("/pupils", status_code=201)
def create_pupil(payload: dict):
    code = _clean_code(str(payload.get("code", "")))
    if db.one("SELECT id FROM pupils WHERE owner=? AND code=?", (owner(), code)):
        raise HTTPException(409, f"There is already a pupil {code}.")
    pid = uuid.uuid4().hex[:10]
    _save_pupil(pid, code, payload, insert=True)
    return _pupil(pid)


@router.patch("/pupils/{pid}")
def update_pupil(pid: str, payload: dict):
    p = _pupil(pid)
    _save_pupil(pid, p["code"], {**p, **payload}, insert=False)
    return _pupil(pid)


@router.delete("/pupils/{pid}", status_code=204)
def delete_pupil(pid: str):
    _pupil(pid)
    db.run("DELETE FROM apdr WHERE pupil_id=? AND owner=?", (pid, owner()))
    db.run("DELETE FROM pupils WHERE id=? AND owner=?", (pid, owner()))


def _save_pupil(pid: str, code: str, p: dict, insert: bool) -> None:
    needs = [n for n in (p.get("needs") or []) if n in {x["key"] for x in NEEDS}]
    area = p.get("need_area") if p.get("need_area") in NEED_AREAS else next(
        (x["area"] for x in NEEDS if x["key"] in needs and x["area"]), "")
    vals = (str(p.get("year_group", ""))[:20], p.get("phase") if p.get("phase") in levels.LEVELS else "primary",
            p.get("status") if p.get("status") in STATUSES else "SEN support", area, db.dumps(needs),
            _redact(str(p.get("summary", "")))[:1500], _redact(str(p.get("strengths", "")))[:800],
            db.dumps([_redact(str(x))[:200] for x in (p.get("provision") or [])][:20]), p.get("next_review") or None)
    if insert:
        db.run("INSERT INTO pupils (year_group, phase, status, need_area, needs, summary, strengths, provision, next_review,"
               " id, owner, code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (*vals, pid, owner(), code))
    else:
        db.run("UPDATE pupils SET year_group=?, phase=?, status=?, need_area=?, needs=?, summary=?, strengths=?,"
               " provision=?, next_review=? WHERE id=? AND owner=?", (*vals, pid, owner()))


@router.get("/pupils/{pid}")
def get_pupil(pid: str):
    p = _pupil(pid)
    p["records"] = [_record_out(r) for r in db.many(
        "SELECT * FROM apdr WHERE pupil_id=? AND owner=? ORDER BY created_at DESC", (pid, owner()))]
    return p


# --------------------------------------------------------------------------- assess-plan-do-review
APDR_PROMPT = f"""You are an experienced SENCO's assistant. A teacher has written a quick note about support for a pupil.
Turn it into a structured assess-plan-do-review record, as the SEND Code of Practice describes the graduated
approach. Keep the teacher's facts; do not add events that did not happen. Write plainly, for school staff.
- assess: what the teacher observed and what it suggests about the barrier (not a diagnosis).
- plan.outcomes: 1-3 SMART outcomes focused on what the pupil will be able to do.
- plan.provision: the adjustments and interventions, using the school's own provision names where they fit.
- plan.who and plan.frequency: who does it and how often (say "to agree" if not given).
- plan.review_in_weeks: a sensible review interval (usually 4-8 weeks).
- do: what was actually done, from the note.
- review.success_criteria: how staff will know it worked.
- pupil_voice and parent_contact: what the note says, or "Not recorded yet".
- missing: anything the record still needs (for example parent views, a baseline).
{GROUNDING}
Answer by calling submit_record once."""

APDR_TOOL = _strict("submit_record", "Submit the structured assess-plan-do-review record.", {
    "assess": STR,
    "plan": {"type": "object", "additionalProperties": False,
             "required": ["outcomes", "provision", "who", "frequency", "review_in_weeks"],
             "properties": {"outcomes": STRS, "provision": STRS, "who": STR, "frequency": STR,
                            "review_in_weeks": {"type": "integer"}}},
    "do": STR,
    "review": {"type": "object", "additionalProperties": False, "required": ["success_criteria"],
               "properties": {"success_criteria": STRS}},
    "pupil_voice": STR, "parent_contact": STR, "missing": STRS,
}, ["assess", "plan", "do", "review", "pupil_voice", "parent_contact", "missing"])


def _record_out(r: dict) -> dict:
    out = dict(r)
    out["record"] = db.loads(r["record"], {})
    out["sources"] = db.loads(r["sources"], [])
    return out


@router.post("/pupils/{pid}/records", status_code=201)
def create_record(pid: str, payload: dict):
    p = _pupil(pid)
    note = _redact(str(payload.get("note", "")).strip())[:4000]
    if len(note) < 10:
        raise HTTPException(400, "Write a few lines about what you tried and what happened.")
    hits = kb.search(owner(), f"{_needs_text(p)} {p['summary']} {note} assess plan do review outcomes provision")
    if config.AI_ENABLED:
        user = (f"{_pupil_brief(p)}\n\nEarlier records:\n{_history(pid)}\n\nTeacher's note:\n{note}\n\n"
                f"Passages:\n{kb.context(hits)}")
        rec = _ai(APDR_PROMPT, user, APDR_TOOL)
    else:
        rec = _mock_record(p, note, hits)
    weeks = max(1, min(26, int(rec.get("plan", {}).get("review_in_weeks") or 6)))
    review = (date.today() + timedelta(weeks=weeks)).isoformat()
    sources = kb.cited(db.dumps(rec), hits)
    rid = uuid.uuid4().hex[:10]
    db.run("INSERT INTO apdr (id, owner, pupil_id, note, record, sources, author, review_date) VALUES (?,?,?,?,?,?,?,?)",
           (rid, owner(), pid, note, db.dumps(rec), db.dumps(sources), str(payload.get("author", ""))[:60], review))
    return _record_out(db.one("SELECT * FROM apdr WHERE id=?", (rid,)))


@router.post("/records/{rid}/approve")
def approve_record(rid: str, payload: dict):
    r = db.one("SELECT * FROM apdr WHERE id=? AND owner=?", (rid, owner()))
    if not r:
        raise HTTPException(404, "Record not found.")
    by = str(payload.get("approved_by", "")).strip()[:60]
    if not by:
        raise HTTPException(400, "Add the name of the member of staff approving this record.")
    rec = payload.get("record") if isinstance(payload.get("record"), dict) else db.loads(r["record"], {})
    review = str(payload.get("review_date") or r["review_date"] or "")[:10] or None
    db.run("UPDATE apdr SET record=?, status='approved', approved_by=?, approved_at=datetime('now'), review_date=?"
           " WHERE id=?", (db.dumps(rec), by, review, rid))
    db.run("UPDATE pupils SET next_review=? WHERE id=? AND owner=?", (review, r["pupil_id"], owner()))
    return _record_out(db.one("SELECT * FROM apdr WHERE id=?", (rid,)))


def _mock_record(p: dict, note: str, hits: list[dict]) -> dict:
    lines = [ln.strip(" -•") for ln in re.split(r"[\n.]+", note) if ln.strip(" -•")]
    cite = f" [{hits[0]['id']}]" if hits else ""
    return {
        "assess": f"{lines[0] if lines else note[:120]}.{cite}",
        "plan": {"outcomes": [f"By the review, {p['code']} will {lines[1].lower() if len(lines) > 1 else 'complete tasks with less adult prompting'}."],
                 "provision": p["provision"][:3] or ["Adapted classwork with visual supports"], "who": "Class teacher with TA",
                 "frequency": "Daily in lessons", "review_in_weeks": 6},
        "do": note[:300],
        "review": {"success_criteria": ["Pupil completes the task with one prompt or fewer", "Pupil says how the support helped"]},
        "pupil_voice": "Not recorded yet", "parent_contact": "Not recorded yet",
        "missing": ["Parent views", "A baseline to measure progress against"],
    }


# --------------------------------------------------------------------------- adapt classwork
ADAPT_PROMPT = f"""You adapt classwork for a pupil with special educational needs, as an experienced SENCO would.
Keep the same learning objective and content; change how it is presented and how the pupil shows what they know.
Use strategies that suit the need given, and the school's own provision where it fits.
- title and objective: the work's title and the same objective in pupil-friendly words.
- instructions: short, one-step, numbered instructions (max 12 words each), concrete, no idioms.
- tasks: each task rewritten, with a scaffold (sentence starter, worked example, choices, visual cue) and
  2-5 small steps.
- word_bank: key subject words with a plain meaning.
- strategies: what you changed and why, each citing the passages.
- check: anything the teacher should check (e.g. a diagram you could not see, timings).
{GROUNDING}
Answer by calling submit_adaptation once."""

ADAPT_TOOL = _strict("submit_adaptation", "Submit the adapted classwork.", {
    "title": STR, "objective": STR, "instructions": STRS,
    "tasks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["task", "scaffold", "steps"],
                                         "properties": {"task": STR, "scaffold": STR, "steps": STRS}}},
    "word_bank": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": ["word", "meaning"], "properties": {"word": STR, "meaning": STR}}},
    "strategies": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                              "required": ["strategy", "why"], "properties": {"strategy": STR, "why": STR}}},
    "check": STRS,
}, ["title", "objective", "instructions", "tasks", "word_bank", "strategies", "check"])


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pptx"):
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        parts = []
        for i, slide in enumerate(prs.slides, 1):
            texts = [sh.text_frame.text for sh in slide.shapes if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip()]
            parts.append(f"Slide {i}:\n" + "\n".join(texts))
        return "\n\n".join(parts)
    if name.endswith(".pdf"):
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            return "\n\n".join(page.get_text() for page in doc)
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    return data.decode("utf8", "ignore")


@router.post("/extract")
async def extract(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "That file is over 15 MB.")
    try:
        text = extract_text(file.filename or "", data)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Couldn't read that file. Try .pptx, .docx, .pdf or .txt, or paste the text.")
    return {"name": file.filename, "text": text.strip()[:20000]}


@router.post("/adapt")
def adapt(payload: dict):
    work = _redact(str(payload.get("work", "")).strip())[:12000]
    if len(work) < 20:
        raise HTTPException(400, "Paste or upload the lesson or worksheet to adapt.")
    needs = [n for n in NEEDS if n["key"] in (payload.get("needs") or [])]
    pupil = _pupil(payload["pupil_id"]) if payload.get("pupil_id") else None
    if not needs and pupil:
        needs = [n for n in NEEDS if n["key"] in pupil["needs"]]
    if not needs:
        raise HTTPException(400, "Choose the need to adapt for, or a pupil.")
    lvl = levels.get(payload.get("phase") or (pupil or {}).get("phase"))
    need_text = ", ".join(n["label"] for n in needs)
    hits = kb.search(owner(), f"{need_text} adapt classwork strategies provision high-quality teaching {work[:400]}")
    if config.AI_ENABLED:
        user = (f"Adapt for: {need_text}. Audience: {lvl.audience}.\n"
                + (f"{_pupil_brief(pupil)}\n" if pupil else "")
                + f"\nThe classwork:\n<work>\n{work}\n</work>\n\nPassages:\n{kb.context(hits)}")
        out = _ai(ADAPT_PROMPT, user, ADAPT_TOOL, max_tokens=8000)
    else:
        out = _mock_adapt(work, need_text, hits)
    out["sources"] = kb.cited(db.dumps(out), hits)
    out["needs"] = [n["label"] for n in needs]
    out["draft"] = True
    out["pupil_code"] = pupil["code"] if pupil else None
    out["id"] = uuid.uuid4().hex[:10]
    db.run("INSERT INTO sen_adaptations (id, owner, pupil_id, data) VALUES (?,?,?,?)",
           (out["id"], owner(), payload.get("pupil_id") or None, db.dumps(out)))
    return out


@router.get("/adaptations/{aid}")
def get_adaptation(aid: str):
    row = db.one("SELECT * FROM sen_adaptations WHERE id=? AND owner=?", (aid, owner()))
    if not row:
        raise HTTPException(404, "That adaptation no longer exists.")
    return db.loads(row["data"], {})


def _mock_adapt(work: str, need_text: str, hits: list[dict]) -> dict:
    lines = [ln.strip(" -•") for ln in work.splitlines() if ln.strip(" -•")]
    cite = f" [{hits[0]['id']}]" if hits else ""
    return {
        "title": lines[0][:80] if lines else "Adapted work", "objective": "Same objective, in smaller steps.",
        "instructions": [ln[:80] for ln in lines[1:5]] or ["Read the task.", "Do one step at a time."],
        "tasks": [{"task": ln[:120], "scaffold": "Sentence starter: 'I think... because...'", "steps": ["Read it", "Underline key words", "Write your answer"]}
                  for ln in lines[1:4]],
        "word_bank": [], "strategies": [{"strategy": "Chunked instructions", "why": f"Reduces load for {need_text}.{cite}"}],
        "check": ["Demo mode: add an Anthropic key for a real adaptation."],
    }


# --------------------------------------------------------------------------- school documents (RAG)
@router.get("/docs")
def list_docs():
    return [{"id": d["id"], "name": d["name"], "words": len(d["text"].split()), "created_at": d["created_at"]}
            for d in db.many("SELECT * FROM kb_docs WHERE owner=? ORDER BY created_at", (owner(),))]


@router.post("/docs", status_code=201)
async def upload_doc(file: UploadFile = File(None), name: str = Form(""), text: str = Form("")):
    if file is not None:
        data = await file.read()
        try:
            text = extract_text(file.filename or "", data)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Couldn't read that file. Try .docx, .pdf or .txt.")
        name = name or file.filename or "School document"
    text = _redact(text).strip()
    if len(text.split()) < 20:
        raise HTTPException(400, "That document has too little text to use.")
    did = uuid.uuid4().hex[:10]
    db.run("INSERT INTO kb_docs (id, owner, name, text) VALUES (?,?,?,?)", (did, owner(), name[:120] or "School document", text[:200000]))
    return {"id": did, "name": name, "words": len(text.split())}


@router.delete("/docs/{did}", status_code=204)
def delete_doc(did: str):
    db.run("DELETE FROM kb_docs WHERE id=? AND owner=?", (did, owner()))


@router.get("/search")
def search(q: str = ""):
    return kb.search(owner(), q)


# --------------------------------------------------------------------------- demo data
DEMO_PROVISION = """Oakfield Primary School (fictional demo school): SEN provision map 2026-27

Wave 1: Quality-first teaching for all
Visual timetables in every classroom. Now/Next boards available from the SENCO. Instructions given one step at a
time and shown visually. Word banks and sentence starters on every writing task. Coloured overlays and cream paper
on request. Movement breaks built into lessons over 30 minutes.

Wave 2: Targeted small-group support
Talk Boost (KS1) and Language Link groups: 3 x 20 minutes a week, run by a trained TA, for speech, language and
communication needs. Precision Teaching for number facts and spelling: 10 minutes daily, TA-led. Zones of
Regulation group: weekly, 30 minutes, for pupils who need help recognising and managing feelings. Social Stories
written with the SENCO for changes to routine.

Wave 3: Specialist and individual support
Speech and language therapy assessment through the NHS service (referral by SENCO). Educational psychologist:
6 visits a year, prioritised by the SENCO. Individual workstation and sensory breaks for autistic pupils who need them.
Sloped boards, pencil grips and laptop access for pupils with motor difficulties.

Reviews: SEN support plans are reviewed with parents three times a year (autumn, spring, summer). Class teachers
log assess-plan-do-review notes at least every half term."""

DEMO_PUPILS = [
    {"code": "Y4-AB", "year_group": "Year 4", "phase": "primary", "status": "SEN support", "needs": ["autism"],
     "summary": "Finds changes to routine and noisy group work hard; may shut down and stop working.",
     "strengths": "Excellent memory for facts, loves trains and maps, follows visual instructions well.",
     "provision": ["Visual timetable", "Now/Next board", "Social Stories", "Individual workstation"], "review_days": -3,
     "note": "Tried a Now/Next board in maths this week. AB finished 3 of 4 tasks on Tues and Thurs, up from 1 last week. "
             "Still struggled when we moved tables on Wed - left the room for 5 min. Mum said he talked about the board at home."},
    {"code": "Y4-CD", "year_group": "Year 4", "phase": "primary", "status": "SEN support", "needs": ["slcn"],
     "summary": "Limited vocabulary; struggles to follow multi-step spoken instructions.",
     "strengths": "Kind and helpful, good at practical tasks and drawing.",
     "provision": ["Language Link group", "Word banks and sentence starters"], "review_days": 9},
    {"code": "Y6-EF", "year_group": "Year 6", "phase": "primary", "status": "EHC plan", "needs": ["mld"],
     "summary": "Working well below age-related expectations in reading and maths.",
     "strengths": "Determined, enjoys PE and helping younger pupils.",
     "provision": ["Precision Teaching", "Word banks and sentence starters", "Visual timetable"], "review_days": 30},
    {"code": "Y5-GH", "year_group": "Year 5", "phase": "primary", "status": "SEN support", "needs": ["adhd", "semh"],
     "summary": "Hard to stay on task for more than a few minutes; frequent conflicts at playtime.",
     "strengths": "Creative, funny, great at building things.",
     "provision": ["Zones of Regulation group", "Movement breaks"], "review_days": 4},
    {"code": "Y3-JK", "year_group": "Year 3", "phase": "primary", "status": "Monitoring", "needs": ["dyslexia"],
     "summary": "Reversals and slow reading despite good spoken vocabulary; parents have raised concerns.",
     "strengths": "Very articulate, loves stories read aloud.",
     "provision": ["Coloured overlays", "Precision Teaching"], "review_days": 20},
]


@router.post("/demo")
def load_demo():
    """Fictional pupils and provision map for a demo. Safe to run twice."""
    if not db.one("SELECT id FROM kb_docs WHERE owner=? AND name LIKE 'Oakfield%'", (owner(),)):
        db.run("INSERT INTO kb_docs (id, owner, name, text) VALUES (?,?,?,?)",
               (uuid.uuid4().hex[:10], owner(), "Oakfield provision map 2026-27", DEMO_PROVISION))
    today = date.today()
    for d in DEMO_PUPILS:
        row = db.one("SELECT id FROM pupils WHERE owner=? AND code=?", (owner(), d["code"]))
        pid = row["id"] if row else uuid.uuid4().hex[:10]
        _save_pupil(pid, d["code"], {**d, "next_review": (today + timedelta(days=d["review_days"])).isoformat()}, insert=not row)
        if not row and d.get("note"):
            db.run("INSERT INTO apdr (id, owner, pupil_id, note, record, status, review_date, created_at) VALUES (?,?,?,?,?,?,?,?)",
                   (uuid.uuid4().hex[:10], owner(), pid, "Started a visual timetable at the start of the autumn term.",
                    db.dumps({"assess": "Anxiety at transitions between lessons.", "plan": {"outcomes": [
                        "AB moves between activities with one visual prompt by October half term."], "provision": [
                        "Visual timetable"], "who": "Class teacher", "frequency": "Daily", "review_in_weeks": 6},
                        "do": "Visual timetable on desk, checked with TA at each change.",
                        "review": {"success_criteria": ["Fewer than 2 refusals a week at transitions"]},
                        "pupil_voice": "AB likes ticking off each picture.", "parent_contact": "Shared at parents' evening.",
                        "missing": []}), "approved", (today - timedelta(days=40)).isoformat(),
                    (today - timedelta(days=42)).isoformat()))
    ab = db.one("SELECT id FROM pupils WHERE owner=? AND code='Y4-AB'", (owner(),))
    if ab and not db.one("SELECT 1 FROM day_plans WHERE owner=? AND pupil_id=? AND day=?", (owner(), ab["id"], _today())):
        save_day(ab["id"], {"periods": DEMO_DAY})
    return list_pupils()


DEMO_DAY = [
    {"subject": "Maths", "time": "9:00", "learn": "Equivalent fractions. Learn that 1/2 and 2/4 are the same amount.\n"
     "Look at the fraction strips\nShade half of each shape\nMatch the fractions that are the same\nTell your partner one thing you found",
     "video_url": "https://www.bbc.co.uk/bitesize/topics/zt9k7ty", "video_title": "BBC Bitesize: fractions"},
    {"subject": "English", "time": "10:15", "learn": "Writing instructions: how to make a jam sandwich.\n"
     "Read the example instructions\nUnderline the bossy verbs\nWrite 4 steps of your own\nCheck each step starts with a verb"},
    {"subject": "Science", "time": "11:30", "learn": "Volcanoes: how they erupt.\n"
     "Watch the short video\nLabel the magma, crater and lava\nSay what happens when pressure builds up",
     "video_url": "https://www.bbc.co.uk/bitesize/topics/zkgg87h", "video_title": "BBC Bitesize: rocks and volcanoes"},
]


@router.get("/demo/note")
def demo_note():
    """A realistic teacher note for the demo (Y4-AB)."""
    return {"code": "Y4-AB", "note": DEMO_PUPILS[0]["note"]}


# --------------------------------------------------------------------------- the pupil's day (learning)
DAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS day_plans (
    owner TEXT NOT NULL DEFAULT '', pupil_id TEXT NOT NULL, day TEXT NOT NULL, periods TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (owner, pupil_id, day)
);
CREATE TABLE IF NOT EXISTS help_requests (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL DEFAULT '', pupil_id TEXT NOT NULL, period INTEGER, message TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'help', seen INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_day_db() -> None:
    with db.connect() as conn:
        conn.executescript(DAY_SCHEMA)


def _safe_url(url: str) -> str:
    url = (url or "").strip()
    return url[:500] if re.match(r"^https://[\w.-]+\.[a-z]{2,}(/\S*)?$", url, re.I) else ""


def _today() -> str:
    return date.today().isoformat()


@router.get("/pupils/{pid}/day")
def get_day(pid: str, day: str = ""):
    p = _pupil(pid)
    d = day or _today()
    row = db.one("SELECT * FROM day_plans WHERE owner=? AND pupil_id=? AND day=?", (owner(), pid, d))
    return {"pupil_id": pid, "code": p["code"], "phase": p["phase"], "day": d,
            "periods": db.loads(row["periods"], []) if row else []}


@router.put("/pupils/{pid}/day")
def save_day(pid: str, payload: dict):
    """Teacher sets the pupil's periods for a day. Each period gets a visual breakdown made by the AI."""
    from concurrent.futures import ThreadPoolExecutor

    from . import agents
    from .auth import current_owner

    p = _pupil(pid)
    d = str(payload.get("day") or _today())[:10]
    raw = [x for x in (payload.get("periods") or []) if isinstance(x, dict)][:8]
    who = owner()

    def build(i_x):
        i, x = i_x
        current_owner.set(who)
        subject = _redact(str(x.get("subject", "")).strip())[:80]
        learn = _redact(str(x.get("learn", "")).strip())[:3000]
        period = {"n": i + 1, "subject": subject or f"Period {i + 1}", "learn": learn,
                  "video_url": _safe_url(str(x.get("video_url", ""))), "video_title": str(x.get("video_title", ""))[:120],
                  "time": str(x.get("time", ""))[:20]}
        old = x.get("breakdown")
        if old and not x.get("regenerate") and x.get("learn_unchanged"):
            period["breakdown"] = old
        elif learn:
            try:
                period["breakdown"] = agents.supports_from_topic(subject, learn, p["phase"])
            except Exception:  # noqa: BLE001
                period["breakdown"] = None
        return period

    with ThreadPoolExecutor(max_workers=4) as pool:
        periods = list(pool.map(build, enumerate(raw)))
    db.run("INSERT INTO day_plans (owner, pupil_id, day, periods) VALUES (?,?,?,?) ON CONFLICT(owner, pupil_id, day) "
           "DO UPDATE SET periods=excluded.periods, updated_at=datetime('now')", (who, pid, d, db.dumps(periods)))
    return get_day(pid, d)


@router.post("/pupils/{pid}/help")
def ask_for_help(pid: str, payload: dict):
    """From the pupil's avatar: 'I'm stuck', or a worry the teacher must see now."""
    _pupil(pid)
    kind = payload.get("kind") if payload.get("kind") in ("help", "safeguarding", "finished") else "help"
    hid = uuid.uuid4().hex[:10]
    db.run("INSERT INTO help_requests (id, owner, pupil_id, period, message, kind) VALUES (?,?,?,?,?,?)",
           (hid, owner(), pid, payload.get("period"), _redact(str(payload.get("message", "")))[:300], kind))
    return {"id": hid}


@router.get("/help")
def list_help():
    rows = db.many("SELECT h.*, p.code FROM help_requests h JOIN pupils p ON p.id=h.pupil_id "
                   "WHERE h.owner=? ORDER BY h.created_at DESC LIMIT 30", (owner(),))
    return rows


@router.post("/help/{hid}/seen")
def help_seen(hid: str):
    db.run("UPDATE help_requests SET seen=1 WHERE id=? AND owner=?", (hid, owner()))
    return {"ok": True}
