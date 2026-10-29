"""Turns the teacher's rough notes into structured slide content.

The model never touches PowerPoint. It only returns JSON (structured outputs, checked
against a schema), and `generator.py` pours that into the teacher's own sample slides.
"""
from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path
from typing import Literal

import anthropic
from PIL import Image
from pydantic import BaseModel, ValidationError

from . import config
from .schemas import CookedSlide, CookRequest, GenerateRequest, SlideContent, SlideSpec

log = logging.getLogger("slidesmith.ai")

SYSTEM_PROMPT = """You write classroom slide content for secondary school teachers.

You receive the teacher's rough notes for specific slide numbers. Turn each into clean, student-friendly slide text.

Rules:
- Return exactly one slide per requested page, using the same page numbers, in the same order.
- Respect the teacher's notes. If they give exact wording, questions, definitions or numbers, keep them as written. Never invent facts, dates, statistics or quotes that the teacher did not give or that you are not certain about.
- Be concise. Bullets are short phrases or single sentences, not paragraphs. Obey the max bullets and max words per bullet limits you are given.
- Use language suited to the year group / level if the teacher mentions it. Otherwise assume secondary school students.
- kind: "title" for an opening slide (use title + subtitle, no bullets); "section" for a divider that only needs a heading (+ optional subtitle); "content" for normal teaching slides (title + bullets); "image" is used when an image is attached to that page (title + at most 3 short bullets, because the picture takes up half the slide).
- If an image is attached, look at it and write text that fits what it actually shows (labels, key points, a question about it). Do not describe the image literally unless the teacher asks.
- notes: 1-3 sentences of speaker notes the teacher can say aloud or use as a prompt for discussion. Leave empty if unnecessary.
- Titles should be short (under 8 words) and must not end with a full stop.
- Match the teacher's spelling conventions (e.g. British vs American) from their notes.
"""

class AIError(RuntimeError):
    """The model gave no usable answer (e.g. it declined); the message is safe to show."""


class _WrittenSlide(BaseModel):
    page: int
    kind: Literal["title", "content", "image", "section"]
    title: str
    subtitle: str
    bullets: list[str]
    notes: str


class _WrittenSlides(BaseModel):
    slides: list[_WrittenSlide]


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=180)


def _parse(system: str, content: list[dict], schema: type[BaseModel]):
    """One structured-output call: the reply is validated against `schema`."""
    # Server-side fallback: if a safety check declines, the API retries on a suitable model.
    response = _client().beta.messages.parse(
        model=config.CLAUDE_MODEL,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise AIError("The AI declined to write these slides. Try rewording the topic.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AIError("The AI's answer was cut short. Try fewer slides.")
    return response.parsed_output


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
    if req.cover:
        lines.append('The cover slide is made separately, so do not use kind "title" for any of these pages.')
    lines.append(
        f"Limits for this slide style: max {capacity['max_bullets']} bullets per slide, "
        f"max {capacity['max_words_per_bullet']} words per bullet."
    )
    lines.append(f"Create exactly {len(req.slides)} slides:")

    blocks: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    for spec in sorted(req.slides, key=lambda s: s.page):
        text = f"\n--- Page {spec.page} ---\nTeacher's notes: {spec.details.strip() or '(none, use the topic)'}"
        if spec.page in images:
            text += "\nAn image is attached to this page (shown next)."
        blocks.append({"type": "text", "text": text})
        if spec.page in images:
            try:
                blocks.append(_encode_image(images[spec.page]))
            except Exception:  # noqa: BLE001
                log.exception("Could not encode image for page %s", spec.page)
    blocks.append({"type": "text", "text": "Now return the slides."})
    return blocks


def _clean(content: SlideContent, capacity: dict) -> SlideContent:
    content.title = content.title.strip().rstrip(".")
    content.bullets = [b.strip() for b in content.bullets if b and b.strip()][: max(capacity["max_bullets"], 3)]
    return content


def _call_claude(req: GenerateRequest, images: dict[int, Path], capacity: dict) -> list[SlideContent]:
    written = _parse(SYSTEM_PROMPT, _build_user_content(req, images, capacity), _WrittenSlides)
    out: list[SlideContent] = []
    for raw in written.slides:
        try:
            out.append(SlideContent.model_validate(raw.model_dump()))
        except ValidationError:
            log.warning("Skipping malformed slide from model: %s", raw)
    return out


# --------------------------------------------------------------------------- #
# Mock mode (no API key): deterministic, lets you demo the whole flow offline
# --------------------------------------------------------------------------- #
def _mock_slide(
    spec: SlideSpec, position: int, total: int, has_image: bool, deck_title: str, has_cover: bool = False
) -> SlideContent:
    parts = [
        re.sub(r"^[\-\*\u2022\d\.\)\s]+", "", p).strip()
        for p in re.split(r"[\n;]+|(?<=[.!?])\s+", spec.details)
        if p.strip()
    ]
    parts = [p for p in parts if p]
    if has_image:
        kind = "image"
    elif position == 0 and total > 1 and not has_cover:
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
            _mock_slide(s, i, total, s.page in images, req.title, req.cover) for i, s in enumerate(specs)
        ]
        return slides, "mock"

    produced = {s.page: _clean(s, capacity) for s in _call_claude(req, images, capacity)}
    total = len(specs)
    result: list[SlideContent] = []
    for i, spec in enumerate(specs):
        slide = produced.get(spec.page)
        if slide is None:
            log.warning("Model skipped page %s; falling back to teacher's raw notes", spec.page)
            slide = _mock_slide(spec, i, total, spec.page in images, req.title, req.cover)
        elif req.cover and slide.kind == "title":
            slide.kind = "content" if slide.bullets else "section"
        result.append(slide)
    return result, "ai"


# --------------------------------------------------------------------------- #
# Cook: a whole lesson deck from a topic and a description
# --------------------------------------------------------------------------- #
COOK_PROMPT = """You plan and write complete classroom slide decks for secondary school teachers.

The teacher gives a topic, a description (year group, what to cover, anything to include) and sometimes pictures.
Plan a well-paced lesson deck and write every slide. The slides are poured into the teacher's own PowerPoint template,
so you only write text: no layout, colours or fonts.

How a good deck flows:
- Cover: a short title (the topic, under 8 words) and a subtitle (year group, subject or a hook) - only from what the teacher said.
- Learning objectives early on ("We will..." / "I can...").
- A starter or hook question to get the class thinking.
- The teaching slides, one idea per slide, building step by step; worked examples where the topic needs them.
- A "check your understanding" slide with 2-4 questions.
- A summary / plenary to finish.
- kind "section" for a divider that only needs a heading (+ optional subtitle); "content" for teaching slides (title + bullets).

Writing rules:
- Bullets are short phrases or single sentences, never paragraphs. Obey the max bullets and max words per bullet limits.
- Pitch the language at the year group in the description; otherwise assume secondary school students.
- Keep anything the teacher states (wording, definitions, numbers) exactly. Never invent statistics, dates, quotes or facts you are not certain about.
- Titles are short (under 8 words) and don't end with a full stop.
- notes: 1-3 sentences the teacher can say aloud, or a prompt for discussion.
- Match the teacher's spelling conventions (British vs American).

Pictures: each attached picture is numbered. Put each one on the single slide where it helps most by setting that slide's
`picture` to its number, and write that slide about what the picture actually shows (at most 3 short bullets, as the picture
takes half the slide). Use every picture once; set `picture` to 0 on slides without one.
"""


class _CookedSlide(BaseModel):
    kind: Literal["content", "section"]
    title: str
    subtitle: str
    bullets: list[str]
    notes: str
    picture: int


class _CookedDeck(BaseModel):
    cover_title: str
    cover_subtitle: str
    slides: list[_CookedSlide]


def _cook_content(req: CookRequest, images: list[Path], capacity: dict) -> list[dict]:
    count = f"exactly {req.slide_count}" if req.slide_count else "between 6 and 10 (your choice, to suit the topic)"
    lines = [
        f"Topic: {req.topic.strip()}",
        f"Description from the teacher: {req.description.strip() or '(none - use the topic)'}",
        f"Number of slides after the cover: {count}.",
        f"Limits for this template: max {capacity['max_bullets']} bullets per slide, "
        f"max {capacity['max_words_per_bullet']} words per bullet.",
        f"Pictures attached: {len(images)}." if images else "No pictures attached.",
    ]
    blocks: list[dict] = [{"type": "text", "text": "\n".join(lines)}]
    for n, path in enumerate(images, start=1):
        blocks.append({"type": "text", "text": f"Picture {n}:"})
        try:
            blocks.append(_encode_image(path))
        except Exception:  # noqa: BLE001
            log.exception("Could not encode picture %s", n)
    blocks.append({"type": "text", "text": "Now plan and write the deck."})
    return blocks


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[\n;]+|(?<=[.!?])\s+", text)
    return [re.sub(r"^[\-\*•\d\.\)\s]+", "", p).strip().rstrip(".") for p in parts if p.strip()]


def _mock_cook(req: CookRequest, image_ids: list[str]) -> tuple[SlideContent, list[CookedSlide]]:
    """Demo mode: a sensible lesson shape from the topic and description, no AI."""
    topic = req.topic.strip()
    facts = [s for s in _sentences(req.description) if s]
    total = req.slide_count or max(6, min(10, 4 + len(image_ids) + (len(facts) + 2) // 3))
    cover = SlideContent(page=0, kind="title", title=topic[:80], subtitle=(facts[0] if facts else "")[:120])
    slides: list[CookedSlide] = [
        CookedSlide(page=0, kind="content", title="Learning objectives",
                    bullets=[f"Understand the key ideas of {topic}", "Use the key words correctly", "Apply what we learn to examples"]),
        CookedSlide(page=0, kind="content", title="Starter", bullets=[f"What do you already know about {topic}?", "Discuss with a partner for 2 minutes"]),
    ]
    teaching = facts[1:] if len(facts) > 1 else facts  # the first sentence is the cover's subtitle
    for start in range(0, len(teaching), 3):
        chunk = teaching[start : start + 3]
        title = " ".join(chunk[0].split()[:5])
        slides.append(CookedSlide(page=0, kind="content", title=title, bullets=chunk))
    for image_id in image_ids:
        slides.append(CookedSlide(page=0, kind="content", title="Look closely", image_id=image_id,
                                  bullets=["What do you notice?", f"How does this link to {topic}?"]))
    closing = [
        CookedSlide(page=0, kind="content", title="Check your understanding",
                    bullets=[f"Explain {topic} in one sentence", "Give an example", "What would you ask next?"]),
        CookedSlide(page=0, kind="content", title="Summary", bullets=[f"Today we explored {topic}", "Remember the key words", "Next lesson: practise and apply"]),
    ]
    # Keep the pictures and the closing slides; trim or pad the teaching slides to the count.
    room = max(total - len(closing), 1)
    pictured = [s for s in slides if s.image_id]
    plain = [s for s in slides if not s.image_id][: max(room - len(pictured), 1)]
    practice = 0
    while len(plain) + len(pictured) < room:
        practice += 1
        plain.append(CookedSlide(page=0, kind="content", title=f"Practice {practice}", bullets=[f"Try a question on {topic}", "Show your working"]))
    return cover, plain + pictured + closing


def cook(req: CookRequest, images: list[tuple[str, Path]], capacity: dict) -> tuple[SlideContent, list[CookedSlide], str]:
    """Returns (cover, numbered slides, mode). Each slide may carry one of the teacher's pictures."""
    ids = [image_id for image_id, _ in images]
    if not config.AI_ENABLED:
        cover, slides = _mock_cook(req, ids)
        mode = "mock"
    else:
        deck = _parse(COOK_PROMPT, _cook_content(req, [p for _, p in images], capacity), _CookedDeck)
        cover = SlideContent(page=0, kind="title", title=deck.cover_title.strip().rstrip("."), subtitle=deck.cover_subtitle.strip())
        used: set[str] = set()
        slides = []
        for raw in deck.slides:
            image_id = ids[raw.picture - 1] if 0 < raw.picture <= len(ids) and ids[raw.picture - 1] not in used else None
            if image_id:
                used.add(image_id)
            slide = CookedSlide(page=0, kind=raw.kind, title=raw.title, subtitle=raw.subtitle, bullets=raw.bullets, notes=raw.notes, image_id=image_id)
            slides.append(slide)
        # A picture the model left out still goes in, on its own slide before the closing ones.
        for image_id in ids:
            if image_id not in used:
                slides.insert(max(len(slides) - 2, 0), CookedSlide(page=0, kind="content", title="Look closely", image_id=image_id))
        mode = "ai"
    for n, slide in enumerate(slides, start=1):
        slide.page = n
        _clean(slide, capacity)
        if slide.image_id:
            slide.bullets = slide.bullets[:3]
    return cover, slides, mode
