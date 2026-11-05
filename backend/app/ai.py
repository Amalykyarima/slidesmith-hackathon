"""Turns the teacher's rough notes into structured slide content.

The model never touches PowerPoint. It only returns JSON (by calling the strict
`submit_slides` tool), and `generator.py` pours that JSON into the teacher's own sample slides.

Newer models (Claude Sonnet 5.5, Fable 5.1) reject a forced tool call (`tool_choice`
"tool"/"any") with a 400, so the tool is offered with `tool_choice: auto`, marked
`strict` so the call always matches the schema, and the prompt asks for it.
"""
from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path

import anthropic
from PIL import Image
from pydantic import ValidationError

from . import config
from .roles import ROLES, role_of
from .schemas import GenerateRequest, SlideContent, SlideSpec

log = logging.getLogger("slidesmith.ai")

SYSTEM_PROMPT = """You write classroom slide content for secondary school teachers.

You receive the teacher's rough notes for specific slide numbers. Turn each into clean, student-friendly slide text.

Rules:
- Return exactly one slide per requested page, using the same page numbers, in the same order.
- A page's notes are either CONTENT or INSTRUCTIONS to you. Content (exact wording, questions, definitions, numbers): keep it as written. Instructions ("write 3 retrieval questions on refraction", "explain Snell's law simply", "make an exam question with answers"): carry them out and write the finished slide; never copy the instruction itself onto the slide. Notes can mix both.
- Never invent facts, dates, statistics or quotes you are not certain about. Use accurate, curriculum-appropriate subject knowledge for the topic.
- The teacher's template slides are listed with a number, heading, role and an example of what she writes there. Each new page copies one of them: set "sample" to that slide's number (0 = let SlideSmith pick), and write the page the way her example is written (same patterns, e.g. "(G) / (A) / (R)" questions, "LO:" lines, labelled boxes). Use a slide that suits the page's job: retrieval questions on her retrieval slide, keywords on her vocabulary slide, questions and their answers on her exam/answers slides. When the teacher chose a slide for a page, use that one.
- Keep the teacher's content complete. Every question, task, definition or example the teacher lists becomes its own bullet, kept word for word, including marks such as "(2)". Never merge two questions into one bullet and never drop one, even if that goes over the bullet limit (up to 8 bullets).
- Tidy rough notes into short bullets: phrases or single sentences, not paragraphs. Stay within the words-per-bullet limit you are given unless that would change the teacher's own wording.
- Routine slides: the teacher's style contains routine slides (listed in the request), such as a retrieval starter, vocabulary, "Turn and Talk", mini-whiteboard practice or an independent task. When a page is one of these, set "role" to its name and make the title follow the example heading for that role (e.g. if the example heading is a topic and a date, write only the new topic: SlideSmith adds the lesson's date in the teacher's own format). If the role has a label, make that label the first bullet. Leave "role" empty for ordinary teaching slides.
- Never add prefixes such as "I do:", "We do:" or "You do:" to titles unless the teacher wrote them.
- Use language suited to the year group / level if the teacher mentions it. Otherwise assume secondary school students.
- kind: "title" for an opening slide (use title + subtitle, no bullets); "section" for a divider that only needs a heading (+ optional subtitle); "content" for normal teaching slides (title + bullets); "image" is used when an image is attached to that page (title + at most 3 short bullets, because the picture takes up half the slide).
- If an image is attached, look at it and write text that fits what it actually shows (labels, key points, a question about it). Do not describe the image literally unless the teacher asks.
- notes: 1-3 sentences of speaker notes the teacher can say aloud or use as a prompt for discussion. Leave empty if unnecessary.
- Titles should be short (under 8 words) and must not end with a full stop.
- deck_title: a short name for this lesson's deck, from what the lesson is actually about (e.g. "Electricity: circuits and mains safety"). Base it on the topic and notes, never on anything else.
- lo: the lesson's learning objective, written the way her template writes it (often a short question, e.g. "How does light change direction?"). keywords: the lesson's key terms, comma-separated (e.g. "Refraction, Normal, Critical angle"). They fill her "LO:" and "Keywords:" lines on every slide.
- Whole lesson (no pages listed, only a topic): plan a complete lesson of exactly the requested number of slides, pages numbered from 1, following the order of her template (her own lessons run in that order): skip template slides that don't fit, and use her teaching slides more than once for the main content. Every slide gets real content for the topic.
- Match the teacher's spelling conventions (e.g. British vs American) from their notes.

Always answer by calling the submit_slides tool once, with every requested page. Do not reply with plain text.
"""

TOOL = {
    "name": "submit_slides",
    "description": "Submit the finished slide content, one entry per requested page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "deck_title": {"type": "string"},
            "lo": {"type": "string"},
            "keywords": {"type": "string"},
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page": {"type": "integer"},
                        "kind": {"type": "string", "enum": ["title", "content", "image", "section"]},
                        "title": {"type": "string"},
                        "subtitle": {"type": "string"},
                        "bullets": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "string"},
                        "role": {"type": "string", "enum": [*ROLES, ""]},
                        "sample": {"type": "integer"},  # her template slide number; 0 = SlideSmith picks
                    },
                    # Strict tools: every field present (empty when unused), nothing extra.
                    "required": ["page", "kind", "title", "subtitle", "bullets", "notes", "role", "sample"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["slides", "deck_title", "lo", "keywords"],
        "additionalProperties": False,
    },
    "strict": True,
}

NUDGE = "Please call the submit_slides tool now, with one entry for every requested page."


def _encode_image(path: Path) -> dict:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(buf.getvalue()).decode(),
        },
    }


def _build_user_content(req: GenerateRequest, images: dict[int, Path], capacity: dict) -> list[dict]:
    lines = []
    if req.title and not req.whole_lesson:  # a whole lesson is named after its topic
        lines.append(f"Deck title: {req.title}")
    if req.topic:
        lines.append(f"Topic / lesson context: {req.topic}")
    if req.instructions:
        lines.append(f"Extra instructions from the teacher: {req.instructions}")
    lines.append(
        f"Limits for this slide style: max {capacity['max_bullets']} bullets per slide, "
        f"max {capacity['max_words_per_bullet']} words per bullet."
    )
    roles = capacity.get("roles") or {}
    if roles:
        lines.append("Routine slides in this teacher's style (role: example heading [label]):")
        for role, ex in roles.items():
            if role == "exit":
                continue
            label = f' [label: "{ex["label"]}"]' if ex.get("label") else ""
            lines.append(f'- {role}: "{ex.get("title", "")}"{label}')
    catalogue = capacity.get("catalogue") or []
    if catalogue:
        lines.append("Her template slides, in the order her lessons use them (number [role] heading: example):")
        for c in catalogue:
            role = f" [{c['role']}]" if c.get("role") else ""
            extra = f" (labelled boxes: {', '.join(c['labels'])})" if c.get("labels") else ""
            body = f": {c['example']}" if c.get("example") else ("" if c.get("holds_text") else " (heading only)")
            if c.get("role") == "exit":
                extra += " (her fixed routine: if used, keep its text exactly)"
            lines.append(f'- #{c["number"]}{role} "{c.get("heading", "")}"{body}{extra}')
    if req.whole_lesson:
        lines.append(f"Write a whole lesson of exactly {req.slide_count} slides (pages 1 to {req.slide_count}).")
        if catalogue:
            lines.append(f"Open the lesson the way she does: page 1 uses her slide #{catalogue[0]['number']} "
                         "(don't add a separate title-only slide unless her template has one).")
        lines.append(f"The teacher's topic and key points:\n{req.brief.strip()}")
    else:
        lines.append(f"Create exactly {len(req.slides)} slides:")

    blocks: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    for spec in sorted(req.slides, key=lambda s: s.page):
        text = f"\n--- Page {spec.page} ---\nTeacher's notes or instructions: {spec.details.strip() or '(none, use the topic)'}"
        if spec.sample:
            heading = next((c.get("heading", "") for c in catalogue if c["number"] == spec.sample), "")
            text += f'\nThe teacher chose her template slide #{spec.sample} ("{heading}") for this page.' 
        if (getattr(spec, "video_url", None) or "").strip():
            text += ("\nThis page shows a video (its picture appears on the slide and opens the video when "
                     "clicked). Don't write the video's web address in the slide text.")
        if spec.page in images:
            text += "\nAn image is attached to this page (shown next)."
        blocks.append({"type": "text", "text": text})
        if spec.page in images:
            try:
                blocks.append(_encode_image(images[spec.page]))
            except Exception:  # noqa: BLE001
                log.exception("Could not encode image for page %s", spec.page)
    blocks.append({"type": "text", "text": "Now call submit_slides."})
    return blocks


def _clean(content: SlideContent, capacity: dict) -> SlideContent:
    content.title = content.title.strip().rstrip(".")
    content.bullets = [b.strip() for b in content.bullets if b and b.strip()][: max(capacity["max_bullets"], 8)]
    if content.role not in ROLES:
        content.role = ""
    numbers = {c["number"] for c in capacity.get("catalogue") or []}
    if content.sample not in numbers:
        content.sample = None  # 0 or unknown: SlideSmith picks
    return content


def _call_claude(req: GenerateRequest, images: dict[int, Path], capacity: dict,
                 extras: dict | None = None) -> list[SlideContent]:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=240)
    messages = [{"role": "user", "content": _build_user_content(req, images, capacity)}]
    block = None
    for attempt in range(2):
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,  # room for the model's own thinking plus the slides
            system=SYSTEM_PROMPT,
            tools=[TOOL],
            tool_choice={"type": "auto"},
            messages=messages,
        )
        block = next((b for b in response.content if getattr(b, "type", "") == "tool_use"
                      and b.name == "submit_slides"), None)
        if block is not None:
            break
        if getattr(response, "stop_reason", "") == "refusal":
            raise RuntimeError("The AI declined to write these slides. Try rewording the notes.")
        log.warning("Model answered without submit_slides (stop_reason=%s); asking again",
                    getattr(response, "stop_reason", "?"))
        # Keep the conversation append-only: its answer, then a reminder.
        messages = [*messages, {"role": "assistant", "content": response.content},
                    {"role": "user", "content": NUDGE}]
    if block is None:
        raise RuntimeError("The AI did not return slide content. Please try again.")
    if extras is not None:  # lesson-wide lines: her "LO:" and "Keywords:" strips
        for key in ("deck_title", "lo", "keywords"):
            value = block.input.get(key)
            if isinstance(value, str) and value.strip():
                extras[key] = " ".join(value.split())[:300]
    out: list[SlideContent] = []
    for raw in block.input.get("slides", []):
        if isinstance(raw, dict):  # strict tools may differ in capitals only ("Content")
            raw = {**raw, **{k: raw[k].strip().lower() for k in ("kind", "role") if isinstance(raw.get(k), str)}}
            if not isinstance(raw.get("sample"), int) or raw["sample"] < 1:
                raw["sample"] = None  # 0 = "SlideSmith picks"
        try:
            out.append(SlideContent.model_validate(raw))
        except ValidationError:
            log.warning("Skipping malformed slide from model: %s", raw)
    return out


# --------------------------------------------------------------------------- #
# Mock mode (no API key): deterministic, lets you demo the whole flow offline
# --------------------------------------------------------------------------- #
def _mock_slide(spec: SlideSpec, position: int, total: int, has_image: bool, deck_title: str) -> SlideContent:
    parts = [
        re.sub(r"^[\-\*\u2022\d\.\)\s]+", "", p).strip()
        for p in re.split(r"[\n;]+|(?<=[.!?])\s+", spec.details)
        if p.strip()
    ]
    parts = [p for p in parts if p]
    if has_image:
        kind = "image"
    elif position == 0 and total > 1:
        kind = "title"
    else:
        kind = "content"

    if not parts:
        return SlideContent(page=spec.page, kind=kind, title=deck_title or f"Slide {spec.page}")
    if len(parts[0]) <= 60:
        title, rest = parts[0].rstrip("."), parts[1:]
    else:
        title, rest = (deck_title or f"Slide {spec.page}"), parts
    if kind == "title":
        return SlideContent(page=spec.page, kind=kind, title=title, subtitle=" ".join(rest)[:120])
    return SlideContent(page=spec.page, kind=kind, title=title, bullets=rest[:6])


def _mock_lesson(req: GenerateRequest, capacity: dict) -> list[SlideContent]:
    """Demo mode, whole lesson: walk her template in order, one slide each, topic as text."""
    catalogue = [c for c in capacity.get("catalogue") or [] if c.get("holds_text")] or capacity.get("catalogue") or []
    lines = [ln.strip() for ln in req.brief.splitlines() if ln.strip()] or [req.title or "Today's lesson"]
    topic = lines[0][:60]
    out = []
    for i in range(req.slide_count or 0):
        c = catalogue[i % len(catalogue)] if catalogue else {}
        heading = c.get("heading") or topic
        out.append(SlideContent(
            page=i + 1, kind="title" if i == 0 else "content",
            # Keep her routine headings ("Retrieval practice"), never an old lesson's topic.
            title=topic if i == 0 else (heading if role_of(heading) else f"{topic}: part {i}"),
            subtitle=" ".join(lines[1:])[:120] if i == 0 else "",
            bullets=[] if i == 0 else (lines[1:4] or [f"Key idea {i} about {topic}"]),
            role=c.get("role", ""), sample=c.get("number"),
        ))
    return out


def generate_content(
    req: GenerateRequest, images: dict[int, Path], capacity: dict, extras: dict | None = None
) -> tuple[list[SlideContent], str]:
    """Returns (slides, mode) where mode is 'ai' or 'mock'. `extras` receives the lesson's
    "lo" and "keywords" when the AI writes them."""
    if req.whole_lesson:
        if not config.AI_ENABLED:
            return _mock_lesson(req, capacity), "mock"
        produced = sorted((_clean(s, capacity) for s in _call_claude(req, images, capacity, extras)),
                          key=lambda s: s.page)
        slides, seen = [], set()
        for s in produced:  # pages 1..N, no repeats, never more than asked
            if s.page not in seen and 1 <= s.page <= (req.slide_count or 0):
                seen.add(s.page)
                slides.append(s)
        if not slides:
            raise RuntimeError("The AI did not return slide content. Please try again.")
        return slides, "ai"

    specs = sorted(req.slides, key=lambda s: s.page)
    if not config.AI_ENABLED:
        total = len(specs)
        slides = [
            _mock_slide(s, i, total, s.page in images, req.title).model_copy(update={"sample": s.sample})
            for i, s in enumerate(specs)
        ]
        return slides, "mock"

    produced = {s.page: _clean(s, capacity) for s in _call_claude(req, images, capacity, extras)}
    total = len(specs)
    result: list[SlideContent] = []
    for i, spec in enumerate(specs):
        slide = produced.get(spec.page)
        if slide is None:
            log.warning("Model skipped page %s; falling back to teacher's raw notes", spec.page)
            slide = _mock_slide(spec, i, total, spec.page in images, req.title)
        if spec.sample:  # the teacher's choice of template slide always wins
            slide = slide.model_copy(update={"sample": spec.sample})
        result.append(slide)
    return result, "ai"
