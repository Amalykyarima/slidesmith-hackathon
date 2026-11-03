"""Turns the teacher's rough notes into structured slide content.

The model never touches PowerPoint. It only returns JSON (via a forced tool call),
and `generator.py` pours that JSON into the teacher's own sample slides.
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
from .roles import ROLES
from .schemas import GenerateRequest, SlideContent, SlideSpec

log = logging.getLogger("slidesmith.ai")

SYSTEM_PROMPT = """You write classroom slide content for secondary school teachers.

You receive the teacher's rough notes for specific slide numbers. Turn each into clean, student-friendly slide text.

Rules:
- Return exactly one slide per requested page, using the same page numbers, in the same order.
- Respect the teacher's notes. If they give exact wording, questions, definitions or numbers, keep them as written. Never invent facts, dates, statistics or quotes that the teacher did not give or that you are not certain about.
- Keep the teacher's content complete. Every question, task, definition or example the teacher lists becomes its own bullet, kept word for word, including marks such as "(2)". Never merge two questions into one bullet and never drop one, even if that goes over the bullet limit (up to 8 bullets).
- Tidy rough notes into short bullets: phrases or single sentences, not paragraphs. Stay within the words-per-bullet limit you are given unless that would change the teacher's own wording.
- Routine slides: the teacher's style contains routine slides (listed in the request), such as a retrieval starter, vocabulary, "Turn and Talk", mini-whiteboard practice or an independent task. When a page is one of these, set "role" to its name and make the title follow the example heading for that role (e.g. if the example heading is a topic and a date, use the new topic and the date the teacher gives). If the role has a label, make that label the first bullet. Leave "role" empty for ordinary teaching slides.
- Never add prefixes such as "I do:", "We do:" or "You do:" to titles unless the teacher wrote them.
- Use language suited to the year group / level if the teacher mentions it. Otherwise assume secondary school students.
- kind: "title" for an opening slide (use title + subtitle, no bullets); "section" for a divider that only needs a heading (+ optional subtitle); "content" for normal teaching slides (title + bullets); "image" is used when an image is attached to that page (title + at most 3 short bullets, because the picture takes up half the slide).
- If an image is attached, look at it and write text that fits what it actually shows (labels, key points, a question about it). Do not describe the image literally unless the teacher asks.
- notes: 1-3 sentences of speaker notes the teacher can say aloud or use as a prompt for discussion. Leave empty if unnecessary.
- Titles should be short (under 8 words) and must not end with a full stop.
- Match the teacher's spelling conventions (e.g. British vs American) from their notes.
"""

TOOL = {
    "name": "submit_slides",
    "description": "Submit the finished slide content, one entry per requested page.",
    "input_schema": {
        "type": "object",
        "properties": {
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
                    },
                    "required": ["page", "kind", "title"],
                },
            }
        },
        "required": ["slides"],
    },
}


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
    if req.title:
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
    lines.append(f"Create exactly {len(req.slides)} slides:")

    blocks: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    for spec in sorted(req.slides, key=lambda s: s.page):
        text = f"\n--- Page {spec.page} ---\nTeacher's notes: {spec.details.strip() or '(none, use the topic)'}"
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
    return content


def _call_claude(req: GenerateRequest, images: dict[int, Path], capacity: dict) -> list[SlideContent]:
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=120)
    response = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "submit_slides"},
        messages=[{"role": "user", "content": _build_user_content(req, images, capacity)}],
    )
    block = next((b for b in response.content if b.type == "tool_use"), None)
    if block is None:
        raise RuntimeError("The model did not return slide content.")
    out: list[SlideContent] = []
    for raw in block.input.get("slides", []):
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


def generate_content(
    req: GenerateRequest, images: dict[int, Path], capacity: dict
) -> tuple[list[SlideContent], str]:
    """Returns (slides, mode) where mode is 'ai' or 'mock'."""
    specs = sorted(req.slides, key=lambda s: s.page)
    if not config.AI_ENABLED:
        total = len(specs)
        slides = [
            _mock_slide(s, i, total, s.page in images, req.title) for i, s in enumerate(specs)
        ]
        return slides, "mock"

    produced = {s.page: _clean(s, capacity) for s in _call_claude(req, images, capacity)}
    total = len(specs)
    result: list[SlideContent] = []
    for i, spec in enumerate(specs):
        slide = produced.get(spec.page)
        if slide is None:
            log.warning("Model skipped page %s; falling back to teacher's raw notes", spec.page)
            slide = _mock_slide(spec, i, total, spec.page in images, req.title)
        result.append(slide)
    return result, "ai"
