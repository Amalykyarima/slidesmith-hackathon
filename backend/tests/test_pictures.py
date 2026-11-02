"""Pages with pictures: the picture goes somewhere sensible and no text is ever lost.

Regression: a page with a picture and four bullet points was built on a picture-only
sample slide (title + photo, no body), so the bullets vanished without a warning.
"""
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches, Pt

from app.generator import build_deck, missing_text
from app.schemas import SlideContent

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

BULLETS = [
    "The alcohol in drinks is a chemical called ethanol.",
    "It is a depressant: it slows down the nervous system.",
    "It is a legal recreational drug for adults.",
    "The liver breaks down alcohol, and this takes time.",
]


def _tb(slide, x, y, w, h, lines, size):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    for i, line in enumerate(lines if isinstance(lines, list) else [lines]):
        p = box.text_frame.paragraphs[0] if i == 0 else box.text_frame.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
    return box


def _img(path, size=(400, 560), color="#88aacc"):
    Image.new("RGB", size, color).save(path)
    return path


def deck(tmp_path, with_text_and_picture: bool) -> Path:
    """A picture-only slide comes first, so it would win on cleanliness alone."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    blank = prs.slide_layouts[6]
    photo = str(_img(tmp_path / "sample.png", color="#55aa55"))

    s = prs.slides.add_slide(blank)  # picture-only: title + big photo, no body
    s.shapes.add_picture(photo, Inches(0.3), Inches(0.3), Inches(4.5), Inches(4.8))
    _tb(s, 5.2, 1.5, 4.0, 1.2, "Nutrition and energy", 20)

    s = prs.slides.add_slide(blank)  # ordinary teaching slide
    _tb(s, 0.4, 0.3, 9.0, 0.8, "Energy", 33)
    _tb(s, 0.5, 1.2, 9.0, 3.8, ["We get energy from food.", "Energy is measured in joules."], 26)

    if with_text_and_picture:
        s = prs.slides.add_slide(blank)  # her own text + picture layout
        _tb(s, 0.4, 0.3, 9.0, 0.8, "Overweight", 33)
        s.shapes.add_picture(photo, Inches(0.5), Inches(1.2), Inches(3.5), Inches(3.8))
        _tb(s, 4.6, 1.2, 5.0, 3.8, ["Energy in is more than energy used.", "Linked to heart disease."], 24)

    path = tmp_path / f"pictures_{with_text_and_picture}.pptx"
    prs.save(path)
    return path


def _pictures(slide):
    return [sh for sh in slide.shapes if sh.shape_type == 13]


@pytest.mark.parametrize("with_text_and_picture", [True, False])
def test_picture_page_keeps_every_line(tmp_path, with_text_and_picture):
    style = deck(tmp_path, with_text_and_picture)
    new = _img(tmp_path / "new.png", color="#cc4444")
    content = SlideContent(page=1, kind="image", title="What is alcohol?", bullets=BULLETS)
    out = OUT / f"picture_page_{with_text_and_picture}.pptx"
    warnings = build_deck(style, [content], {1: new}, out)

    slide = Presentation(str(out)).slides[0]
    assert missing_text(slide, content) == []
    assert not any("missing" in w for w in warnings)
    texts = " ".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)
    assert "Nutrition and energy" not in texts  # the picture-only sample wasn't used
    pics = _pictures(slide)
    assert len(pics) == 1  # the new picture, and no leftover sample photo

    body = next(sh for sh in slide.shapes if sh.has_text_frame and "ethanol" in sh.text_frame.text)
    pic = pics[0]
    overlap_x = min(body.left + body.width, pic.left + pic.width) - max(body.left, pic.left)
    overlap_y = min(body.top + body.height, pic.top + pic.height) - max(body.top, pic.top)
    assert overlap_x <= 0 or overlap_y <= 0  # picture beside the text, not on top of it
    if with_text_and_picture:
        assert "Overweight" not in texts and pic.left < body.left  # her layout: picture left, text right


def test_text_that_cannot_fit_anywhere_is_reported(tmp_path):
    """A style with only a picture-only slide: the page is still built, with a clear warning."""
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_picture(str(_img(tmp_path / "p.png")), Inches(0.3), Inches(0.3), Inches(4.5), Inches(5.5))
    _tb(s, 5.2, 1.5, 4.0, 1.2, "Only a heading here", 20)
    style = tmp_path / "picture_only.pptx"
    prs.save(style)

    content = SlideContent(page=3, kind="content", title="What is alcohol?", bullets=BULLETS)
    warnings = build_deck(style, [content], {}, OUT / "picture_only_out.pptx")
    assert any(w.startswith("Slide 3: 4 line(s)") and "ethanol" in w for w in warnings)
    assert len(Presentation(str(OUT / "picture_only_out.pptx")).slides) == 1


def test_no_text_lost_across_a_routine_lesson(tmp_path):
    """Every page of a routine lesson, with and without pictures, shows all its text."""
    from test_routines import routine_deck

    style = routine_deck(tmp_path)
    pic = _img(tmp_path / "liver.png", (600, 400), "#aa5544")
    contents = [
        SlideContent(page=1, title="Alcohol   5th Nov 2026", role="retrieval",
                     bullets=["Retrieval Practice:", "What is a drug? (1)", "What is addiction? (1)"]),
        SlideContent(page=2, title="Turn and Talk", bullets=["Why is alcohol a drug?"]),
        SlideContent(page=3, kind="image", title="What is alcohol?", bullets=BULLETS),
        SlideContent(page=4, title="Short-term effects", bullets=["Slower reactions", "Poor judgement"]),
        SlideContent(page=5, kind="image", title="Independent Task", bullets=["1. Describe a depressant. (1)"]),
    ]
    out = OUT / "routine_pictures.pptx"
    warnings = build_deck(style, contents, {3: pic, 5: pic}, out)
    slides = list(Presentation(str(out)).slides)
    assert len(slides) == len(contents)
    for slide, content in zip(slides, contents):
        assert missing_text(slide, content) == [], content.title
    assert not any("missing" in w for w in warnings)
    assert len(_pictures(slides[2])) == 1 and len(_pictures(slides[4])) == 1
