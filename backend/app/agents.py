"""The agent team that turns a teacher's request into a reviewed lesson.

    Orchestrator ─► input guardrails ─► Planner ─► SEN Adapter ─► Reviewer ─► output guardrails
                                                                        │
                                       nothing worrying ◄───────────────┴──► something to check
                                       build the deck                       escalate to the teacher
                                                                            (human-in-the-loop)

- Orchestrator: reads the request and switches modes: plan a whole lesson or polish her notes,
  which level, whether SEN scaffolding is needed, how strict the review is.
- Planner: writes the slide text (ai.py, the original SlideSmith writer).
- SEN Adapter: simpler wording where it helps, symbol words, key-word cards, task-step cards and a
  lesson schedule for Now/Next boards.
- Reviewer: a second model that checks accuracy, age fit, safeguarding and inclusion, on top of the
  rule-based guardrails (guardrails.py) that never depend on a model.

Every step emits events, so the teacher watches the agents work in real time (SSE), and every run
keeps its state (session state) so she can leave, come back, edit and approve.

Each agent returns JSON through a strict tool; none of them touches PowerPoint. Without an API key
every agent has a deterministic stand-in, so the whole flow demos offline.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import anthropic

from . import ai, config, db, guardrails, levels, pictos
from .auth import current_owner
from .guardrails import Flag
from .schemas import GenerateRequest, SlideContent

log = logging.getLogger("slidesmith.agents")

AGENTS = {
    "orchestrator": "Orchestrator",
    "guardrails": "Guardrails",
    "planner": "Planner",
    "sen": "SEN Adapter",
    "reviewer": "Reviewer",
    "builder": "Builder",
    "teacher": "Teacher",
}

SEN_HINTS = re.compile(
    r"\b(sen|send|senco|ehcp|autis\w*|asd|adhd|dyslexi\w*|dyspraxi\w*|neurodiverg\w*|eal|"
    r"visual (support|timetable|schedule)s?|now[ /-]?next|symbols?|widgit|makaton|scaffold\w*)\b",
    re.I,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    request TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{}',
    events TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Live runs (one server process). The database copy survives restarts and serves history.
_live: dict[str, dict] = {}
_lock = threading.Lock()


def init_db() -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------- run state
def _save(run: dict) -> None:
    db.run("UPDATE runs SET status=?, state=?, events=? WHERE id=?",
           (run["status"], db.dumps(run["state"]), db.dumps(run["events"]), run["id"]))


def emit(run: dict, agent: str, message: str, status: str = "done", data: dict | None = None) -> None:
    event = {"n": len(run["events"]) + 1, "t": round(time.time(), 2), "agent": agent,
             "name": AGENTS.get(agent, agent), "status": status, "message": message, "data": data or {}}
    with _lock:
        run["events"].append(event)
    _save(run)


def set_status(run: dict, status: str) -> None:
    run["status"] = status  # saved by emit(), together with the event that announces it
    emit(run, "orchestrator", f"Run is now: {status.replace('_', ' ')}", "status", {"status": status})


def get(run_id: str, owner: str) -> dict | None:
    with _lock:
        live = _live.get(run_id)
    if live and live["owner"] == owner:
        return live
    row = db.one("SELECT * FROM runs WHERE id=? AND owner=?", (run_id, owner))
    if not row:
        return None
    return {"id": row["id"], "owner": row["owner"], "status": row["status"],
            "request": db.loads(row["request"], {}), "state": db.loads(row["state"], {}),
            "events": db.loads(row["events"], [])}


def public(run: dict) -> dict:
    s = run["state"]
    return {
        "id": run["id"], "status": run["status"], "events": run["events"],
        "level": s.get("level"), "sen": s.get("sen"), "modes": s.get("modes", []),
        "title": s.get("title", ""), "lo": s.get("lo", ""), "keywords": s.get("keywords", ""),
        "slides": s.get("slides", []), "original": s.get("original", {}),
        "flags": s.get("flags", []), "supports": s.get("supports"),
        "generation_id": s.get("generation_id"), "error": s.get("error"),
        "requires_review": s.get("requires_review", False),
    }


def create(req: GenerateRequest, owner: str) -> dict:
    run = {"id": uuid.uuid4().hex[:12], "owner": owner, "status": "running",
           "request": req.model_dump(mode="json"), "state": {}, "events": []}
    db.run("INSERT INTO runs (id, owner, status, request) VALUES (?,?,?,?)",
           (run["id"], owner, run["status"], db.dumps(run["request"])))
    with _lock:
        _live[run["id"]] = run
    return run


def start(run: dict, req: GenerateRequest, images: dict[int, Path], capacity: dict,
          builder: Callable[[dict, list[SlideContent]], dict]) -> None:
    def work():
        current_owner.set(run["owner"])  # the thread acts for the same teacher
        try:
            execute(run, req, images, capacity, builder)
        except Exception as exc:  # noqa: BLE001
            log.exception("Run %s failed", run["id"])
            run["state"]["error"] = _friendly(exc)
            emit(run, "orchestrator", run["state"]["error"], "error")
            set_status(run, "failed")

    threading.Thread(target=work, daemon=True, name=f"run-{run['id']}").start()


def _friendly(exc: Exception) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY."
    if isinstance(exc, anthropic.RateLimitError):
        return "The AI service is busy right now. Please try again in a moment."
    if isinstance(exc, anthropic.APIError):
        return f"The AI service returned an error: {getattr(exc, 'message', exc)}"
    if isinstance(exc, RuntimeError):
        return str(exc)
    return "Something went wrong while the agents were working. Please try again."


def _pause() -> None:
    """Demo mode answers instantly; a short beat lets the teacher see each agent take its turn."""
    if not config.AI_ENABLED:
        time.sleep(0.45)


# --------------------------------------------------------------------------- the pipeline
def execute(run: dict, req: GenerateRequest, images: dict[int, Path], capacity: dict,
            builder: Callable[[dict, list[SlideContent]], dict]) -> None:
    state = run["state"]
    lvl = levels.get(req.level)

    # 1. Orchestrator: decide the modes for this run.
    everything = " ".join([req.topic, req.instructions, req.brief, *(s.details for s in req.slides)])
    sen = req.sen if req.sen is not None else (lvl.key == "primary" or bool(SEN_HINTS.search(everything)))
    plan_mode = "plan a whole lesson" if req.whole_lesson else "polish the teacher's notes"
    modes = [f"Level: {lvl.label}", f"Planner: {plan_mode}",
             "SEN scaffolding: on" + ("" if req.sen is not None else " (auto)") if sen else "SEN scaffolding: off",
             f"Review strictness: {'high' if lvl.key == 'primary' else 'standard'}"]
    state.update(level=lvl.key, sen=sen, modes=modes)
    emit(run, "orchestrator", "Reading the request and choosing modes", "working")
    _pause()
    emit(run, "orchestrator", " · ".join(modes), "done", {"modes": modes})

    # 2. Input guardrails: nothing personal reaches the AI, no injected instructions.
    emit(run, "guardrails", "Checking the request before it reaches the AI", "working")
    req, found, injected = _guard_input(req)
    msg = []
    if found:
        msg.append(f"removed {', '.join(sorted(set(found)))}")
    if injected:
        msg.append("neutralised an instruction aimed at the AI")
    emit(run, "guardrails", ("Input: " + "; ".join(msg)) if msg else "Input is clean: no personal data, no injected instructions",
         "warn" if msg else "done")

    # 3. Planner.
    emit(run, "planner", f"Writing the slides ({plan_mode}, for {lvl.audience})", "working")
    extras: dict[str, str] = {}
    contents, mode = ai.generate_content(req, images, capacity, extras)
    _pause()
    slides = [c.model_dump() for c in contents]
    state["title"] = req.title.strip() or extras.get("deck_title") or (req.brief.strip().splitlines() or [""])[0][:120]
    state["lo"] = req.lo.strip() or extras.get("lo", "")
    state["keywords"] = req.keywords.strip() or extras.get("keywords", "")
    state["ai_mode"] = mode
    state["slides"] = slides
    emit(run, "planner", f"Wrote {len(slides)} slides" + (" (demo mode: your text as typed)" if mode == "mock" else ""),
         "done", {"pages": [s["page"] for s in slides]})

    # 4. SEN Adapter.
    if sen:
        emit(run, "sen", "Adapting for SEN: simpler wording, symbols, key-word and step cards", "working")
        adapted, supports, changed = sen_adapt(slides, state, lvl)
        _pause()
        state["original"] = {str(p): b for p, b in changed.items()}
        state["slides"] = slides = adapted
        state["supports"] = supports
        emit(run, "sen", f"Simplified {len(changed)} slide(s); made {len(supports['key_words'])} key-word cards, "
             f"{len(supports['task_steps'])} step cards and a {len(supports['schedule'])}-step Now/Next schedule",
             "done", {"changed": sorted(changed)})
    else:
        state["supports"] = None

    # 5. Reviewer (a second model) + rule-based output guardrails.
    emit(run, "reviewer", "Checking accuracy, age fit, safeguarding and inclusion", "working")
    flags = [f.dict() for f in guardrails.check_slides(slides, lvl)]
    flags += [f.dict() for f in review(slides, state, lvl, req)]
    _pause()
    state["flags"] = flags
    escalate = guardrails.needs_review(flags)
    state["requires_review"] = escalate
    counts = {s: sum(1 for f in flags if f["severity"] == s) for s in ("block", "check", "info")}
    emit(run, "reviewer", f"{counts['block']} must-fix, {counts['check']} to check, {counts['info']} notes",
         "warn" if escalate else "done", {"counts": counts})

    # 6. Escalate to the teacher, or build straight away.
    if escalate:
        emit(run, "orchestrator", "Escalating to the teacher: please review the flagged slides before the deck is built",
             "waiting")
        set_status(run, "needs_review")
        return
    build(run, builder, note="Nothing needed a human: building the deck")


def build(run: dict, builder: Callable[[dict, list[SlideContent]], dict], note: str) -> dict:
    emit(run, "builder", note, "working")
    contents = [SlideContent.model_validate({k: v for k, v in s.items() if k in SlideContent.model_fields})
                for s in run["state"]["slides"]]
    generation = builder(run, contents)
    run["state"]["generation_id"] = generation["id"]
    emit(run, "builder", f"Deck ready: {len(contents)} slides in the teacher's own style", "done",
         {"generation_id": generation["id"]})
    set_status(run, "built")
    return generation


def approve(run: dict, slides: list[dict], accepted: list[int], builder) -> dict:
    """The teacher's decision. Rule-based 'block' flags can't be waved through: they must be fixed."""
    lvl = levels.get(run["state"].get("level"))
    by_page = {s["page"]: s for s in run["state"]["slides"]}
    for edit in slides:
        page = edit.get("page")
        if page in by_page:
            for key in ("title", "subtitle", "bullets", "notes"):
                if key in edit:
                    by_page[page][key] = edit[key]
    run["state"]["slides"] = list(by_page.values())
    blocking = [f for f in guardrails.check_slides(run["state"]["slides"], lvl) if f.severity == "block"]
    if blocking:
        emit(run, "guardrails", f"Still blocked: {blocking[0].message}", "warn")
        raise ValueError(f"Slide {blocking[0].page}: {blocking[0].message}")
    n_edited = len(slides)
    emit(run, "teacher", f"Teacher approved ({n_edited} slide(s) edited, {len(accepted)} flag(s) accepted)", "done")
    return build(run, builder, note="Building the approved deck")


# --------------------------------------------------------------------------- input guard
def _guard_input(req: GenerateRequest) -> tuple[GenerateRequest, list[str], bool]:
    found: list[str] = []
    injected = False

    def clean(text: str) -> str:
        nonlocal injected
        text, kinds = guardrails.redact(text)
        found.extend(kinds)
        text, inj = guardrails.neutralise_injection(text)
        injected = injected or inj
        return text

    data = req.model_dump()
    for key in ("title", "topic", "instructions", "brief", "lo", "keywords"):
        data[key] = clean(data[key])
    for s in data["slides"]:
        s["details"] = clean(s["details"])
    return GenerateRequest.model_validate(data), found, injected


# --------------------------------------------------------------------------- SEN adapter
SEN_PROMPT = """You are a SEN (special educational needs) specialist teaching assistant. You adapt lesson slides
so neurodivergent pupils (autism, ADHD, dyslexia) and pupils with lower reading ages can access them,
without losing the teacher's content.

Rules:
- simplified: for each slide whose bullets would be hard to read, rewrite its bullets: short sentences
  (max 10 words), one idea per bullet, concrete words, no idioms or sarcasm, explain subject words.
  Keep the teacher's questions and tasks (same meaning, same marks like "(2)"). Leave a slide out if it
  is already simple.
- symbols: for every slide, 1-3 plain, concrete words for symbols (e.g. "volcano", "listen", "write").
  Prefer nouns and classroom actions a child can picture. Never abstract words.
- key_words: up to 8 of the lesson's key terms, each with a child-friendly meaning (max 12 words)
  and one concrete symbol word.
- task_steps: for each task or activity in the lesson, break it into 3-6 numbered steps, each
  starting with a verb ("Read...", "Underline...", "Write..."), each with one symbol word.
- schedule: the lesson as 4-7 short stages for a Now/Next board / visual timetable
  (e.g. "Starter", "Learn", "Practise", "Check", "Finish"), each with one symbol word.
- Never invent facts. Never add content the teacher did not ask for.

Answer by calling submit_adaptations once."""

SEN_TOOL = {
    "name": "submit_adaptations",
    "description": "Submit SEN adaptations and visual supports for the lesson.",
    "input_schema": {
        "type": "object",
        "properties": {
            "simplified": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["page", "bullets"],
                "properties": {"page": {"type": "integer"}, "bullets": {"type": "array", "items": {"type": "string"}}}}},
            "symbols": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["page", "words"],
                "properties": {"page": {"type": "integer"}, "words": {"type": "array", "items": {"type": "string"}}}}},
            "key_words": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["word", "meaning", "symbol"],
                "properties": {"word": {"type": "string"}, "meaning": {"type": "string"}, "symbol": {"type": "string"}}}},
            "task_steps": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["page", "task", "steps"],
                "properties": {"page": {"type": "integer"}, "task": {"type": "string"}, "steps": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["text", "symbol"],
                    "properties": {"text": {"type": "string"}, "symbol": {"type": "string"}}}}}}},
            "schedule": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["label", "symbol"],
                "properties": {"label": {"type": "string"}, "symbol": {"type": "string"}}}},
        },
        "required": ["simplified", "symbols", "key_words", "task_steps", "schedule"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _slides_brief(slides: list[dict]) -> str:
    out = []
    for s in slides:
        body = "\n".join(f"  - {b}" for b in s.get("bullets", []))
        out.append(f"Page {s['page']} [{s.get('kind')}] {s.get('title', '')}\n{body}".rstrip())
    return "\n".join(out)


def call_tool(system: str, user: str, tool: dict, max_tokens: int = 8000) -> dict:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=180)
    messages = [{"role": "user", "content": user}]
    for _ in range(2):
        resp = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=max_tokens, system=system,
                                      tools=[tool], tool_choice={"type": "auto"}, messages=messages)
        block = next((b for b in resp.content if getattr(b, "type", "") == "tool_use" and b.name == tool["name"]), None)
        if block is not None:
            return block.input
        messages = [*messages, {"role": "assistant", "content": resp.content},
                    {"role": "user", "content": f"Please call {tool['name']} now."}]
    raise RuntimeError("An agent did not return its answer. Please try again.")


def sen_adapt(slides: list[dict], state: dict, lvl: levels.Level) -> tuple[list[dict], dict, dict[int, list[str]]]:
    if config.AI_ENABLED:
        user = (f"Audience: {lvl.audience}. Lesson: {state.get('title', '')}. "
                f"Key words: {state.get('keywords', '') or '(choose them)'}.\n\nSlides:\n{_slides_brief(slides)}")
        raw = call_tool(SEN_PROMPT, user, SEN_TOOL)
    else:
        raw = _mock_sen(slides, state)

    by_page = {s["page"]: dict(s) for s in slides}
    changed: dict[int, list[str]] = {}
    for item in raw.get("simplified", []):
        page, bullets = item.get("page"), [b.strip() for b in item.get("bullets", []) if b and b.strip()]
        if page in by_page and bullets and by_page[page].get("kind") in ("content", "image") \
                and bullets != by_page[page].get("bullets"):
            changed[page] = by_page[page].get("bullets", [])
            by_page[page]["bullets"] = bullets[:8]
    symbols_by_page = {i.get("page"): i.get("words", [])[:3] for i in raw.get("symbols", [])}
    for page, s in by_page.items():
        s["symbols"] = [pictos.symbol(w) for w in symbols_by_page.get(page, []) if w.strip()]
    _, supports, _ = _apply_supports([], raw, state)
    return [by_page[s["page"]] for s in slides], supports, changed


_VERB = re.compile(r"^(read|write|label|draw|answer|explain|describe|discuss|list|match|complete|underline|"
                   r"circle|find|compare|calculate|sort|plan|design|talk|tell|think|use|look|cut|glue|stick|colour|color|"
                   r"ask|put|tidy|wash|count|measure|build|share|listen|watch|check|stop|wait|sit)\b", re.I)


def _concrete(text: str) -> list[str]:
    words = [w for w in re.findall(r"[A-Za-z]{4,}", text) if w.lower() not in guardrails_stop]
    hits = [w for w in words if pictos.find(w)]
    return hits[:2]


guardrails_stop = {"what", "which", "when", "where", "that", "this", "with", "from", "they", "their", "have",
                   "your", "about", "into", "using", "make", "does", "will", "each", "more", "some", "slide"}


def _mock_sen(slides: list[dict], state: dict) -> dict:
    """Demo stand-in: split long bullets, pick symbol words, and build cards from the slides."""
    simplified, symbols, tasks = [], [], []
    for s in slides:
        bullets = s.get("bullets", [])
        short = []
        for b in bullets:
            parts = [p.strip(" ,;") for p in re.split(r";|,\s(?:and|but|so)\s|\.\s", b) if p.strip(" ,;")]
            short.extend(parts if len(b.split()) > 12 and len(parts) > 1 else [b])
        if short != bullets:
            simplified.append({"page": s["page"], "bullets": short})
        symbols.append({"page": s["page"], "words": _concrete(" ".join([s.get("title", ""), *bullets])) or ["book"]})
        steps = [b for b in bullets if _VERB.match(b)]
        if steps:
            tasks.append({"page": s["page"], "task": s.get("title", "Task"),
                          "steps": [{"text": st, "symbol": _VERB.match(st).group(1).lower()} for st in steps[:6]]})
    kw = [k.strip() for k in (state.get("keywords") or "").split(",") if k.strip()]
    if not kw:
        kw = list(dict.fromkeys(w for s in slides for w in _concrete(s.get("title", ""))))
    key_words = [{"word": k, "meaning": f"A key word from today's lesson on {state.get('title') or 'this topic'}.",
                  "symbol": k} for k in kw[:8]]
    schedule = [{"label": "Starter", "symbol": "start"}, {"label": "Listen and learn", "symbol": "listen"},
                {"label": "Practise", "symbol": "write"}, {"label": "Check", "symbol": "check"},
                {"label": "Finish", "symbol": "finish"}]
    return {"simplified": simplified, "symbols": symbols, "key_words": key_words, "task_steps": tasks,
            "schedule": schedule}


# --------------------------------------------------------------------------- reviewer
REVIEW_PROMPT = """You are an experienced head of department reviewing AI-written lesson slides before a teacher
uses them. You are a second pair of eyes, independent of the writer.

Flag only real problems:
- accuracy: a statement that is wrong, or that you are not confident is true (numbers, dates, definitions).
- age_fit: content, vocabulary or examples unsuitable for the stated audience.
- safeguarding: sensitive content (self-harm, abuse, drugs, violence, sexual content, extremism) that needs
  care, a content warning or a check with the safeguarding lead; anything that could upset or expose a pupil.
- inclusion: stereotypes, exclusionary examples, or wording that makes the slide inaccessible.

severity: "check" when the teacher should look before using the slide; "info" for minor suggestions.
Keep each message to one sentence and give a concrete suggestion. Return an empty list when the slides are fine.
Answer by calling submit_review once."""

REVIEW_TOOL = {
    "name": "submit_review",
    "description": "Submit review flags for the slides.",
    "input_schema": {
        "type": "object",
        "properties": {"flags": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["page", "severity", "kind", "message", "suggestion"],
            "properties": {
                "page": {"type": "integer"},
                "severity": {"type": "string", "enum": ["check", "info"]},
                "kind": {"type": "string", "enum": ["accuracy", "age_fit", "safeguarding", "inclusion"]},
                "message": {"type": "string"},
                "suggestion": {"type": "string"},
            }}}},
        "required": ["flags"],
        "additionalProperties": False,
    },
    "strict": True,
}

# Topics that always deserve a human look at the youngest levels, even in demo mode.
SENSITIVE = re.compile(r"\b(suicide|self[- ]harm|abuse|drugs?|alcohol|weapons?|war|death|sex\w*|extremis\w*|"
                       r"terroris\w*|racis\w*|slavery|holocaust|genocide)\b", re.I)


def review(slides: list[dict], state: dict, lvl: levels.Level, req: GenerateRequest) -> list[Flag]:
    flags: list[Flag] = []
    pages = {s["page"] for s in slides}
    if config.AI_ENABLED:
        user = (f"Audience: {lvl.audience} ({lvl.label}). Lesson: {state.get('title', '')}.\n"
                f"Teacher's topic: {req.topic or req.brief[:500]}\n\nSlides:\n{_slides_brief(slides)}")
        raw = call_tool(REVIEW_PROMPT, user, REVIEW_TOOL, max_tokens=6000)
        for f in raw.get("flags", []):
            if f.get("page") in pages or f.get("page") == 0:
                flags.append(Flag(page=f["page"], severity=f.get("severity", "info"), kind=f.get("kind", "accuracy"),
                                  message=f.get("message", ""), source="reviewer", suggestion=f.get("suggestion", "")))
    # Sensitive topics are escalated by rule at primary and secondary, whatever the model said.
    if lvl.key != "university":
        for s in slides:
            m = SENSITIVE.search(guardrails.slide_text(s))
            if m and not any(f.page == s["page"] and f.kind == "safeguarding" for f in flags):
                flags.append(Flag(page=s["page"], severity="check", kind="safeguarding",
                                  message=f"Sensitive topic (\"{m.group(0)}\") for {lvl.label}: check it fits your "
                                          "school's policy and warn pupils beforehand if needed.",
                                  source="rules", suggestion="Add a content note, or talk to your safeguarding lead."))
    return flags


# --------------------------------------------------------------------------- visual supports on their own
def supports_from_topic(topic: str, details: str, level_key: str) -> dict:
    """For a TA who needs cards now, without a deck: Now/Next, timetable, steps and key words."""
    lvl = levels.get(level_key)
    topic, _ = guardrails.redact(topic)
    details, _ = guardrails.redact(details)
    details, _ = guardrails.neutralise_injection(details)
    state = {"title": topic.strip()[:120], "keywords": ""}
    if config.AI_ENABLED:
        user = (f"Audience: {lvl.audience}. There are no slides: make visual supports for this lesson, activity "
                f"or part of the school day.\nTopic: {topic}\nWhat happens / what the pupil must do:\n{details}\n"
                "Return empty lists for simplified and symbols.")
        raw = call_tool(SEN_PROMPT, user, SEN_TOOL)
    else:
        raw = _mock_topic(topic, details)
    _, supports, _ = _apply_supports([], raw, state)
    return supports


def _apply_supports(slides: list[dict], raw: dict, state: dict):
    """sen_adapt's second half, shared with supports_from_topic."""
    by_page = {s["page"]: dict(s) for s in slides}
    supports = {
        "title": state.get("title", ""),
        "credit": pictos.CREDIT,
        "key_words": [{**pictos.symbol(k.get("symbol") or k.get("word", "")), "word": k.get("word", ""),
                       "meaning": k.get("meaning", "")} for k in raw.get("key_words", [])[:8] if k.get("word")],
        "task_steps": [{"page": t.get("page"), "task": t.get("task", ""),
                        "steps": [{**pictos.symbol(st.get("symbol") or st.get("text", "")), "text": st.get("text", "")}
                                  for st in t.get("steps", [])[:6]]}
                       for t in raw.get("task_steps", [])[:6] if t.get("steps")],
        "schedule": [{**pictos.symbol(st.get("symbol") or st.get("label", "")), "label": st.get("label", "")}
                     for st in raw.get("schedule", [])[:7] if st.get("label")],
    }
    return [by_page[s["page"]] for s in slides], supports, {}


def _mock_topic(topic: str, details: str) -> dict:
    lines = [re.sub(r"^[\-\*•\d\.\)\s]+", "", ln).strip() for ln in re.split(r"[\n;]+", details) if ln.strip()]
    lines = [ln for ln in lines if ln]
    steps = [{"text": ln[:80], "symbol": (_VERB.match(ln).group(1).lower() if _VERB.match(ln) else
                                          (_concrete(ln) or [ln])[0])} for ln in lines[:6]]
    words = list(dict.fromkeys(w.lower() for w in _concrete(topic + " " + details)))[:6]
    return {
        "simplified": [], "symbols": [],
        "key_words": [{"word": w, "meaning": f"A word we will use in {topic or 'this lesson'}.", "symbol": w} for w in words],
        "task_steps": [{"page": 0, "task": topic or "My task", "steps": steps}] if steps else [],
        "schedule": [{"label": "Arrive and settle", "symbol": "sit"}, {"label": topic[:30] or "Lesson", "symbol": (words or ["book"])[0]},
                     {"label": "Break", "symbol": "break"}, {"label": "Tidy up", "symbol": "tidy"},
                     {"label": "Home time", "symbol": "home"}],
    }
