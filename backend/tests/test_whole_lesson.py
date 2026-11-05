"""Whole lessons from a topic, per-slide instructions, and choosing her template slide."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation

from app import ai, config
from app.generator import build_deck
from app.main import app
from app.pptx_analysis import analyze_presentation, template_catalogue
from app.schemas import GenerateRequest, SlideContent
from tests.test_style_fidelity import lesson_deck

FIX = Path(__file__).parent / "fixtures"


def _names(slide) -> set[str]:
    return {sh.name for sh in slide.shapes}


def test_catalogue_lists_her_slides_in_order(tmp_path):
    prs = Presentation(str(lesson_deck(tmp_path)))
    cat = template_catalogue(prs, analyze_presentation(prs))
    assert [c["number"] for c in cat] == [1, 2, 3]
    assert cat[0]["role"] == "retrieval" and cat[1]["role"] == "vocabulary"
    assert "definition" in cat[1]["labels"] or cat[1]["labels"]  # her labelled boxes are named


def test_chosen_template_slide_is_used(tmp_path):
    style = lesson_deck(tmp_path)
    sample_names = _names(Presentation(str(style)).slides[2])  # her task slide
    out = tmp_path / "chosen.pptx"
    # An ordinary page would normally not pick slide 3 first; the choice makes it.
    build_deck(style, [SlideContent(page=1, title="Snell's law", bullets=["n = sin i / sin r"], sample=3)], {}, out)
    assert _names(Presentation(str(out)).slides[0]) >= sample_names - {""} or \
        len(_names(Presentation(str(out)).slides[0]) & sample_names) >= len(sample_names) - 1


def test_bad_choice_is_ignored(tmp_path):
    out = tmp_path / "x.pptx"
    build_deck(lesson_deck(tmp_path), [SlideContent(page=1, title="Hello", bullets=["a"], sample=99)], {}, out)
    assert len(Presentation(str(out)).slides) == 1


def test_request_needs_slides_or_a_topic():
    with pytest.raises(ValueError):
        GenerateRequest(style_id="x")
    with pytest.raises(ValueError):
        GenerateRequest(style_id="x", brief="Refraction", slide_count=None)
    req = GenerateRequest(style_id="x", brief="Refraction of light", slide_count=8)
    assert req.whole_lesson


def test_prompt_has_catalogue_instructions_and_choice(tmp_path):
    prs = Presentation(str(lesson_deck(tmp_path)))
    capacity = {"max_bullets": 6, "max_words_per_bullet": 14, "catalogue": template_catalogue(prs, analyze_presentation(prs))}
    req = GenerateRequest(style_id="x", slides=[
        {"page": 1, "details": "Write 3 retrieval questions (G/A/R) on last lesson: reflection", "sample": 1},
        {"page": 2, "details": "Keyword: refraction"},
    ])
    text = "\n".join(b["text"] for b in ai._build_user_content(req, {}, capacity) if b["type"] == "text")
    assert '- #1 [retrieval]' in text and '- #2 [vocabulary]' in text
    assert "chose her template slide #1" in text
    assert "Teacher's notes or instructions: Write 3 retrieval questions" in text
    assert "INSTRUCTIONS" in ai.SYSTEM_PROMPT and "never copy the instruction" in ai.SYSTEM_PROMPT

    whole = GenerateRequest(style_id="x", brief="Refraction of light\nYear 10, include Snell's law", slide_count=9)
    text = "\n".join(b["text"] for b in ai._build_user_content(whole, {}, capacity) if b["type"] == "text")
    assert "whole lesson of exactly 9 slides" in text and "include Snell's law" in text


def test_whole_lesson_with_ai(monkeypatch, tmp_path):
    seen = {}

    class Planner:
        def create(self, **kwargs):
            seen.update(kwargs)
            assert "sample" in kwargs["tools"][0]["input_schema"]["properties"]["slides"]["items"]["required"]
            slides = [{"page": n, "kind": "content", "title": f"Slide {n}", "subtitle": "", "bullets": ["x"],
                       "notes": "", "role": "", "sample": 3 if n > 1 else 0} for n in range(1, 7)]
            slides.append({**slides[0], "page": 9})  # beyond what was asked: dropped
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="submit_slides", input={"slides": slides})],
                                   stop_reason="tool_use")

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=Planner()))
    prs = Presentation(str(lesson_deck(tmp_path)))
    capacity = {"max_bullets": 6, "max_words_per_bullet": 14, "catalogue": template_catalogue(prs, analyze_presentation(prs))}
    req = GenerateRequest(style_id="x", brief="Refraction of light", slide_count=6)
    slides, mode = ai.generate_content(req, {}, capacity)
    assert mode == "ai" and [s.page for s in slides] == [1, 2, 3, 4, 5, 6]
    assert slides[0].sample is None and slides[1].sample == 3  # 0 means "SlideSmith picks"


def test_teacher_choice_beats_the_ai(monkeypatch, tmp_path):
    class Disagrees:
        def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="submit_slides", input={"slides": [
                {"page": 1, "kind": "content", "title": "Q", "subtitle": "", "bullets": ["a"], "notes": "",
                 "role": "", "sample": 2}]})], stop_reason="tool_use")

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=Disagrees()))
    prs = Presentation(str(lesson_deck(tmp_path)))
    capacity = {"max_bullets": 6, "max_words_per_bullet": 14, "catalogue": template_catalogue(prs, analyze_presentation(prs))}
    slides, _ = ai.generate_content(GenerateRequest(style_id="x", slides=[{"page": 1, "details": "q", "sample": 3}]), {}, capacity)
    assert slides[0].sample == 3


def test_whole_lesson_demo_mode_through_the_api():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        r = c.post("/api/generate", json={"style_id": style["id"], "title": "Refraction",
                                          "brief": "Refraction of light\nLight slows in glass\nBends towards the normal",
                                          "slide_count": 5, "slides": []})
        assert r.status_code == 201, r.text
        assert len(r.json()["slides"]) == 5
        bad = c.post("/api/generate", json={"style_id": style["id"], "slides": []})
        assert bad.status_code == 422


def test_long_heading_stops_before_her_badge(tmp_path):
    from PIL import Image
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    head = s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(0.8))
    head.text_frame.text = "Exam questions"
    body = s.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(4))
    body.text_frame.text = "(G)\n(A)\n(R)"
    badge = tmp_path / "badge.png"
    Image.new("RGB", (100, 100), "#1f4e79").save(badge)
    s.shapes.add_picture(str(badge), Inches(6), Inches(0.25), Inches(0.9), Inches(0.9))
    style = tmp_path / "exam.pptx"
    prs.save(style)

    out = tmp_path / "out.pptx"
    build_deck(style, [SlideContent(page=1, title="Exam questions on total internal reflection",
                                    bullets=["What is the critical angle?"])], {}, out)
    slide = Presentation(str(out)).slides[0]
    title = next(sh for sh in slide.shapes if sh.has_text_frame and "total internal" in sh.text_frame.text)
    pic = next(sh for sh in slide.shapes if sh.shape_type == 13)
    assert title.left + title.width <= pic.left  # the heading no longer runs under the badge


def _labelled_style(tmp_path) -> Path:
    """Her slides carry the old lesson's "LO:" and "Keywords:" lines, one of them split
    over two boxes (a bare "LO:" with the question beside it)."""
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    lo = s.shapes.add_textbox(Inches(0.3), Inches(0.05), Inches(8), Inches(0.35)).text_frame.paragraphs[0]
    r = lo.add_run(); r.text = "LO:"; r.font.bold = True; r.font.size = Pt(10)
    r = lo.add_run(); r.text = " How does light change direction?"; r.font.italic = True; r.font.size = Pt(10)
    t = s.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(0.8)).text_frame
    t.text = "Refraction of light"
    t.paragraphs[0].runs[0].font.size = Pt(32)
    s.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(4)).text_frame.text = "Light slows in glass\nIt bends towards the normal"
    kw = s.shapes.add_textbox(Inches(0.3), Inches(7.0), Inches(8), Inches(0.35)).text_frame.paragraphs[0]
    r = kw.add_run(); r.text = "Keywords: "; r.font.bold = True; r.font.size = Pt(10)
    r = kw.add_run(); r.text = "Refraction, Prism"; r.font.size = Pt(10)
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    head = s2.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(0.8)).text_frame
    head.text = "Exam questions"
    head.paragraphs[0].runs[0].font.size = Pt(32)
    s2.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(4)).text_frame.text = "(G)\n(A)\n(R)"
    for left, width, text in ((0.3, 0.5, "LO:"), (0.85, 6, "How does light change direction?")):
        box = s2.shapes.add_textbox(Inches(left), Inches(0.05), Inches(width), Inches(0.35)).text_frame
        box.text = text
        box.paragraphs[0].runs[0].font.size = Pt(10)
        box.paragraphs[0].runs[0].font.italic = text != "LO:"
    path = tmp_path / "labelled.pptx"
    prs.save(path)
    return path


def _all_text(slide) -> str:
    return " || ".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)


def test_lo_and_keywords_strips_get_the_new_lesson(tmp_path):
    out = tmp_path / "tir.pptx"
    build_deck(_labelled_style(tmp_path), [
        SlideContent(page=1, title="Total internal reflection", bullets=["Light can reflect inside glass"], sample=1),
        SlideContent(page=2, title="Exam questions", bullets=["(G) What is the critical angle?"], sample=2),
    ], {}, out, lesson_labels={"lo": "When does light stay inside glass?", "keywords": "Critical angle, Optical fibre"})
    one, two = Presentation(str(out)).slides
    assert "LO: When does light stay inside glass?" in _all_text(one)
    assert "Keywords: Critical angle, Optical fibre" in _all_text(one)
    lo_runs = next(sh for sh in one.shapes if sh.has_text_frame and sh.text_frame.text.startswith("LO:")).text_frame.paragraphs[0].runs
    assert lo_runs[0].font.bold and lo_runs[1].font.italic  # her label stays bold, the words italic
    text = _all_text(two)
    assert "When does light stay inside glass?" in text and "How does light change direction?" not in text
    assert "Refraction, Prism" not in _all_text(one)


def test_without_new_words_old_lesson_lines_are_removed(tmp_path):
    out = tmp_path / "plain.pptx"
    build_deck(_labelled_style(tmp_path), [
        SlideContent(page=1, title="Exam questions", bullets=["(G) What is the critical angle?"], sample=2),
    ], {}, out)
    text = _all_text(Presentation(str(out)).slides[0])
    assert "How does light change direction?" not in text and "LO:" not in text


def test_ai_writes_lo_and_keywords(monkeypatch, tmp_path):
    class Writes:
        def create(self, **kwargs):
            assert {"lo", "keywords"} <= set(kwargs["tools"][0]["input_schema"]["required"])
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="submit_slides", input={
                "lo": "When does light stay inside glass?", "keywords": "Critical angle,  Optical fibre",
                "slides": [{"page": 1, "kind": "content", "title": "TIR", "subtitle": "", "bullets": ["a"],
                            "notes": "", "role": "", "sample": 0}]})], stop_reason="tool_use")

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=Writes()))
    extras = {}
    ai.generate_content(GenerateRequest(style_id="x", brief="TIR", slide_count=2), {},
                        {"max_bullets": 6, "max_words_per_bullet": 14, "catalogue": []}, extras)
    assert extras == {"lo": "When does light stay inside glass?", "keywords": "Critical angle, Optical fibre"}


def test_teacher_typed_lo_wins():
    from app.main import _labels
    req = GenerateRequest(style_id="x", brief="t", slide_count=2, lo="  My own LO  ")
    assert _labels(req, {"lo": "AI LO", "keywords": "AI words"}) == {"lo": "My own LO", "keywords": "AI words"}
