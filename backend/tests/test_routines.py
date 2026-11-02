"""Routine-based lesson decks (retrieval, Turn and Talk, I do / We do / You do).

The fixture copies the structure of a real secondary-science deck that broke the
first version: a retrieval slide whose question box uses a bigger font than its
header, LO / Keywords labels on every slide, "Climate 1 'I do'" badges, captions
laid over pictures, grouped picture cards, and auto-numbered task lists.
"""
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.generator import build_deck, page_role
from app.pptx_analysis import analyze_presentation, style_roles
from app.roles import role_of
from app.schemas import SlideContent

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def _tb(slide, x, y, w, h, lines, size, numbered=False):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    lines = lines if isinstance(lines, list) else [lines]
    for i, line in enumerate(lines):
        p = box.text_frame.paragraphs[0] if i == 0 else box.text_frame.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
        if numbered:
            ppr = p._p.get_or_add_pPr()
            etree.SubElement(ppr, qn("a:buAutoNum")).set("type", "arabicPeriod")
    return box


def _img(path, color):
    Image.new("RGB", (600, 400), color).save(path)
    return str(path)


def routine_deck(tmp_path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    photo = _img(tmp_path / "photo.png", "#3366aa")
    card = _img(tmp_path / "card.png", "#aa6633")

    def labels(s):
        _tb(s, 0.6, 0.05, 11, 0.4, "LO: How do we know something is healthy?", 14)
        _tb(s, 0.6, 7.05, 11, 0.4, "Keywords: Balanced diet, carbohydrate, lipid", 14)

    # 0  Retrieval: header 27pt, question box 28pt (bigger font than the header!)
    s = prs.slides.add_slide(blank)
    _tb(s, 0.1, 0.0, 12.9, 0.7, "Nutrients            24th Sep 2026", 27)
    _tb(s, 0.1, 0.9, 10.8, 6.0, ["Retrieval Practice:", "Which organ system breaks food down?",
                                 "How would you define a healthy diet?", "Why do we need food?"], 28)
    _tb(s, 0.0, 6.9, 13.3, 0.5, "RETRIEVAL-FOOTER", 10)

    # 1  Turn and Talk
    s = prs.slides.add_slide(blank)
    _tb(s, 0.4, 0.4, 12.4, 0.8, "Turn and Talk", 33)
    _tb(s, 0.5, 1.3, 11.3, 5.4, ["What vitamins can you think of?", "Where are they found?"], 31)
    _tb(s, 0.0, 6.9, 13.3, 0.4, "TT-FOOTER", 10)
    labels(s)

    # 2  'I do' teaching slide: badge, body, and a captioned picture card
    s = prs.slides.add_slide(blank)
    _tb(s, 0.4, 0.4, 11.0, 0.8, "Energy", 33)
    _tb(s, 12.0, 0.0, 1.3, 0.3, "Climate 1 ‘I do’", 6)
    _tb(s, 0.6, 1.5, 7.0, 4.0, ["We get energy from food.", "Energy is measured in joules."], 28)
    s.shapes.add_picture(photo, Inches(8.2), Inches(1.5), Inches(4.5), Inches(4.5))
    _tb(s, 8.3, 4.6, 4.3, 1.3, ["Caption sitting on the photo", "second caption line"], 14)
    _tb(s, 0.0, 6.9, 13.3, 0.4, "IDO-FOOTER", 10)
    labels(s)

    # 3  Grouped picture cards (content we can't refill)
    s = prs.slides.add_slide(blank)
    _tb(s, 0.4, 0.4, 11.0, 0.8, "Benedict's test", 30)
    _tb(s, 12.0, 0.0, 1.3, 0.3, "Climate 1 ‘I do’", 6)
    grp = s.shapes.add_group_shape()
    grp.shapes.add_picture(card, Inches(0.5), Inches(1.5), Inches(3.5), Inches(3.0))
    tb = grp.shapes.add_textbox(Inches(0.5), Inches(4.6), Inches(3.5), Inches(1.5))
    tb.text_frame.text = "Reagent: Benedict's solution"

    # 4  Independent Practice with an auto-numbered list
    s = prs.slides.add_slide(blank)
    _tb(s, 0.6, 0.3, 12.0, 1.2, "Independent Practice", 44)
    _tb(s, 0.6, 1.7, 11.5, 4.5, ["List the seven nutrients.", "Where can we find nutrition labels?"], 29, numbered=True)
    _tb(s, 0.0, 6.9, 13.3, 0.4, "YOUDO-FOOTER", 10)
    labels(s)

    # 5  Exit routine (must never be used for lesson content)
    s = prs.slides.add_slide(blank)
    _tb(s, 0.4, 0.4, 11.0, 0.8, "Lesson Exit Routines", 33)
    _tb(s, 0.6, 1.5, 11.0, 4.0, ["Return all equipment.", "Tuck chairs in."], 24)

    path = tmp_path / "routine_style.pptx"
    prs.save(path)
    return path


def _texts(slide) -> list[str]:
    return [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]


def test_routine_slides_are_recognised(tmp_path):
    prs = Presentation(str(routine_deck(tmp_path)))
    infos = analyze_presentation(prs)
    assert [i.role for i in infos] == ["retrieval", "turn_and_talk", "i_do", "i_do", "you_do", "exit"]

    retrieval = infos[0]
    header = next(s for s in prs.slides[0].shapes if s.shape_id == retrieval.title_id)
    assert header.text_frame.text.startswith("Nutrients")  # not the bigger-font question box

    ido = infos[2]
    body = next(s for s in prs.slides[2].shapes if s.shape_id == ido.body_id)
    assert body.text_frame.text.startswith("We get energy")  # not the badge or the caption

    stale_text = [s.text_frame.text for s in prs.slides[1].shapes if s.shape_id in infos[1].stale_ids]
    assert any(t.startswith("LO:") for t in stale_text) and any(t.startswith("Keywords:") for t in stale_text)

    assert infos[3].complex  # grouped cards

    roles = style_roles(prs, infos)
    assert roles["retrieval"] == {"title": "Nutrients 24th Sep 2026", "label": "Retrieval Practice:"}


def test_role_of_matches_routine_headings():
    assert role_of("Retrieval Practice:") == "retrieval"
    assert role_of("Tier 2 Vocabulary") == "vocabulary"
    assert role_of("Turn and Talk") == "turn_and_talk"
    assert role_of("7. MWB") == "we_do"
    assert role_of("Climate 2 ‘We do’") == "we_do"
    assert role_of("Independent Task") == "you_do"
    assert role_of("Homelearning") == "homework"
    assert role_of("Super stretch") == "stretch"
    assert role_of("Climate 1 ‘I do’") == "i_do"
    assert role_of("Short-term effects") is None
    assert role_of("How do we know something is healthy?") is None
    assert page_role(SlideContent(page=1, title="Alcohol 5th Nov", bullets=["Retrieval Practice:", "Q1"])) == "retrieval"


def test_pages_use_the_sample_with_the_same_role(tmp_path):
    style = routine_deck(tmp_path)
    questions = [f"Question {n} about drugs and digestion? ({n % 2 + 1})" for n in range(1, 6)]
    contents = [
        SlideContent(page=1, kind="title", title="Alcohol 5th Nov 2026", role="retrieval",
                     bullets=["Retrieval Practice:", *questions]),
        SlideContent(page=2, kind="content", title="Turn and Talk", bullets=["Why is alcohol a drug?"]),
        SlideContent(page=3, kind="content", title="Short-term effects", bullets=["Slower reactions", "Poor judgement"]),
        SlideContent(page=4, kind="content", title="Long-term effects", bullets=["Liver damage", "Heart disease"]),
        SlideContent(page=5, kind="content", title="Independent Task",
                     bullets=["1. Describe a depressant. (1)", "2. Give two effects. (2)"]),
    ]
    out = OUT / "routines.pptx"
    build_deck(style, contents, {}, out)
    slides = list(Presentation(str(out)).slides)
    assert len(slides) == 5

    texts = [" ".join(_texts(s)) for s in slides]
    assert "RETRIEVAL-FOOTER" in texts[0]
    assert all(q in texts[0] for q in questions)  # every retrieval question kept
    assert "TT-FOOTER" in texts[1]
    assert "IDO-FOOTER" in texts[2] and "IDO-FOOTER" in texts[3]  # ordinary pages -> 'I do' sample
    assert "YOUDO-FOOTER" in texts[4]

    for t in texts:
        assert "Lesson Exit Routines" not in t and "Benedict" not in t
        assert "LO: How do we know" not in t and "Keywords: Balanced" not in t
        assert "Caption sitting on the photo" not in t

    # Title keeps no list numbering; auto-numbered body lines lose their typed "1."
    you_do = slides[4]
    title = next(s for s in you_do.shapes if s.has_text_frame and s.text_frame.text == "Independent Task")
    ppr = title.text_frame.paragraphs[0]._p.find(qn("a:pPr"))
    assert ppr is not None and ppr.find(qn("a:buNone")) is not None
    body = next(s for s in you_do.shapes if s.has_text_frame and "depressant" in s.text_frame.text)
    assert [p.text for p in body.text_frame.paragraphs] == ["Describe a depressant. (1)", "Give two effects. (2)"]


def test_reused_photo_link_and_label(tmp_path):
    """A big photo reused on two slides is lesson content, sample hyperlinks are dropped,
    and a repeated label line keeps the sample's unnumbered formatting."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    photo = _img(tmp_path / "fish.png", "#c08040")
    for heading in ("Turn and Talk", "Independent Task"):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        _tb(s, 0.4, 0.4, 8.0, 0.8, heading, 33)
        _tb(s, 0.5, 1.4, 7.0, 5.0, ["Old question one?", "Old question two?"], 28)
        s.shapes.add_picture(photo, Inches(8.5), Inches(1.4), Inches(4.3), Inches(5.0))
    s = prs.slides.add_slide(prs.slide_layouts[6])
    head = _tb(s, 0.1, 0.0, 12.9, 0.7, "Nutrients   24th Sep 2026", 27)
    head.text_frame.paragraphs[0].runs[0].hyperlink.address = "https://example.com/old-lesson"
    box = _tb(s, 0.1, 0.9, 10.8, 6.0, ["Retrieval Practice:"], 28)
    q = box.text_frame.add_paragraph(); q.text = "Which organ system breaks food down?"
    etree.SubElement(q._p.get_or_add_pPr(), qn("a:buAutoNum")).set("type", "arabicPeriod")
    style = tmp_path / "reuse.pptx"
    prs.save(style)

    infos = analyze_presentation(Presentation(str(style)))
    assert infos[0].kind == "image" and infos[1].kind == "image"  # reused photo is content

    out = OUT / "reuse.pptx"
    build_deck(style, [
        SlideContent(page=1, title="Turn and Talk", bullets=["New question?"]),
        SlideContent(page=2, title="Alcohol   5th Nov 2026", role="retrieval",
                     bullets=["Retrieval Practice:", "What is a drug? (1)", "What is addiction? (1)"]),
    ], {}, out)
    result = list(Presentation(str(out)).slides)
    assert not any(sh.shape_type == 13 for sh in result[0].shapes)  # sample photo removed

    header = next(sh for sh in result[1].shapes if sh.has_text_frame and sh.text_frame.text.startswith("Alcohol"))
    assert header.text_frame.paragraphs[0].runs[0].hyperlink.address is None
    body = next(sh for sh in result[1].shapes if sh.has_text_frame and "Retrieval" in sh.text_frame.text)
    paras = [p._p.find(qn("a:pPr")) for p in body.text_frame.paragraphs]
    numbered = [pp is not None and pp.find(qn("a:buAutoNum")) is not None for pp in paras]
    assert numbered == [False, True, True]
