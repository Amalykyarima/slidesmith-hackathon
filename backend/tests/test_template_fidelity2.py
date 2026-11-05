"""Fixes from the science teacher's electricity lesson: unique slide names (previews),
coloured G/A/R labels, video icons, one-off slides, topic-named decks, preview retry."""
import io
import zipfile
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from app import generator
from app.generator import build_deck
from app.main import app
from app.pptx_analysis import analyze_presentation, one_off_slides
from app.schemas import SlideContent
from tests.test_style_fidelity import lesson_deck

FIX = Path(__file__).parent / "fixtures"


def test_slide_parts_are_unique_even_after_retries(tmp_path, monkeypatch):
    calls = Counter()
    real = generator.missing_text

    def picky(slide, content):  # the first samples tried "don't fit": discarded, then retried
        calls[content.page] += 1
        return ["x"] if calls[content.page] < 3 else real(slide, content)

    monkeypatch.setattr(generator, "missing_text", picky)
    out = tmp_path / "many.pptx"
    build_deck(lesson_deck(tmp_path), [SlideContent(page=n, title=f"Slide {n}", bullets=["a", "b"]) for n in range(1, 7)],
               {}, out)
    names = [n for n in zipfile.ZipFile(out).namelist() if n.startswith("ppt/slides/slide")]
    assert len(names) == len(set(names)) == 6
    assert sorted(names) == sorted(f"ppt/slides/slide{n}.xml" for n in range(1, 7))
    assert [s.shapes.title.text_frame.text if s.shapes.title else
            next(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in Presentation(str(out)).slides][0]


def _gar_style(tmp_path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    head = s.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(9), Inches(0.8)).text_frame
    head.text = "Retrieval practice"
    head.paragraphs[0].runs[0].font.size = Pt(32)
    body = s.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(4)).text_frame
    for i, (label, colour, q) in enumerate([("(G)", "00B050", " What is meant by refraction?"),
                                            ("(A)", "FFC000", " Which way does it bend?"),
                                            ("(R)", "FF0000", " Explain why a ray along the normal goes straight on.")]):
        p = body.paragraphs[0] if i == 0 else body.add_paragraph()
        r = p.add_run(); r.text = label; r.font.bold = True; r.font.color.rgb = RGBColor.from_string(colour)
        r = p.add_run(); r.text = q
    # A photo with a YouTube button on it, and a grouped "I do" badge on its corner.
    photo, icon = tmp_path / "photo.png", tmp_path / "yt.png"
    Image.new("RGB", (400, 300), "#88aacc").save(photo)
    Image.new("RGB", (60, 40), "#ff0000").save(icon)
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    h2 = s2.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(6), Inches(0.8)).text_frame
    h2.text = "Refraction of light"
    h2.paragraphs[0].runs[0].font.size = Pt(32)
    s2.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(6), Inches(4)).text_frame.text = (
        "Refraction is the change in direction of light at a boundary\nLight slows down in glass\n"
        "It bends towards the normal as it enters\nThe reverse happens as it leaves")
    s2.shapes.add_picture(str(photo), Inches(8), Inches(1.5), Inches(5), Inches(5))
    s2.shapes.add_picture(str(icon), Inches(12), Inches(6), Inches(0.8), Inches(0.5))
    grp = s2.shapes.add_group_shape()
    grp.shapes.add_picture(str(icon), Inches(12), Inches(1.6), Inches(0.8), Inches(0.5))
    grp.shapes.add_textbox(Inches(12), Inches(1.5), Inches(0.8), Inches(0.2)).text_frame.text = "I do"
    s3 = prs.slides.add_slide(prs.slide_layouts[6])
    s3.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(9), Inches(0.8)).text_frame.text = "Requisition x 15"
    s3.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(4)).text_frame.text = "Glass block\nRay box"
    path = tmp_path / "gar.pptx"
    prs.save(path)
    return path


def _runs(slide):
    body = max((sh for sh in slide.shapes if sh.has_text_frame), key=lambda sh: len(sh.text_frame.text))
    return [[(r.text, r.font.bold, str(r.font.color.rgb) if r.font.color and r.font.color.type else None)
             for r in p.runs] for p in body.text_frame.paragraphs]


def test_gar_labels_keep_their_colours_and_questions_stay_plain(tmp_path):
    out = tmp_path / "q.pptx"
    build_deck(_gar_style(tmp_path), [SlideContent(page=1, title="Retrieval practice", sample=1, bullets=[
        "(G) What is meant by electric current?", "(A) Which meter measures current?",
        "(R) Explain why all bulbs go out in a series circuit.", "Bonus: what is a fuse for?"])], {}, out)
    paras = _runs(Presentation(str(out)).slides[0])
    assert paras[0][0] == ("(G)", True, "00B050") and paras[1][0][2] == "FFC000" and paras[2][0][2] == "FF0000"
    assert paras[0][1][0].strip() == "What is meant by electric current?" and paras[0][1][2] is None
    assert not paras[0][1][1]  # the question is not bold
    assert all(r[2] is None and not r[1] for r in paras[3])  # a line with no label: plain, never red


def test_video_button_goes_with_its_photo_but_her_badge_stays(tmp_path):
    out = tmp_path / "pic.pptx"
    build_deck(_gar_style(tmp_path), [SlideContent(page=1, title="Circuits", sample=2, bullets=["A circuit is a loop"])],
               {}, out)
    slide = Presentation(str(out)).slides[0]
    assert [sh.shape_type for sh in slide.shapes].count(13) == 0  # photo and YouTube icon gone
    assert any(sh.shape_type == 6 for sh in slide.shapes)  # the grouped "I do" badge stays
    body = next(sh for sh in slide.shapes if sh.has_text_frame and "loop" in sh.text_frame.text)
    assert body.width > Inches(6)  # the text uses the room the photo left


def test_one_off_slides_are_found_and_skipped(tmp_path):
    style = _gar_style(tmp_path)
    assert one_off_slides(analyze_presentation(Presentation(str(style)))) == [3]
    out = tmp_path / "t.pptx"
    build_deck(style, [SlideContent(page=1, kind="title", title="Electricity", subtitle="Circuits")], {}, out, skip={3})
    assert "Requisition" not in " ".join(sh.text_frame.text for sh in Presentation(str(out)).slides[0].shapes if sh.has_text_frame)


def test_choosing_slides_through_the_api(tmp_path):
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("gar.pptx", _gar_style(tmp_path).read_bytes())}).json()
        assert style["excluded"] == [3]  # her one-off "Requisition" slide, switched off at upload
        assert c.patch(f"/api/styles/{style['id']}", json={"excluded": [1, 3]}).json()["excluded"] == [1, 3]
        assert c.patch(f"/api/styles/{style['id']}", json={"excluded": [1, 2, 3]}).status_code == 400
        assert c.patch(f"/api/styles/{style['id']}", json={"excluded": "x"}).status_code == 400
        assert c.patch(f"/api/styles/{style['id']}", json={"name": "Physics"}).json()["excluded"] == [1, 3]


def test_whole_lesson_is_named_after_its_topic():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        r = c.post("/api/generate", json={"style_id": style["id"], "title": "Alcohol", "slides": [],
                                          "brief": "Electricity\nCircuits and mains safety", "slide_count": 3}).json()
        assert r["title"] == "Electricity"
        d = c.get(r["download_url"])
        assert "electricity" in d.headers["content-disposition"].lower() and "alcohol" not in d.headers["content-disposition"].lower()


def test_previews_can_be_drawn_again():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        gen = c.post("/api/build", json={"style_id": style["id"], "slides": [{"page": 1, "title": "Hi"}]}).json()
        r = c.post(f"/api/generations/{gen['id']}/previews")
        assert r.status_code in (200, 400)  # 400 only where LibreOffice isn't installed
        assert c.post("/api/generations/nope/previews").status_code == 404


def test_exit_routine_is_kept_word_for_word(tmp_path):
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(8), Inches(0.8)).text_frame.text = "Lesson Exit Routines"
    s.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(8), Inches(4)).text_frame.text = (
        "All equipment should be returned to the correct place.\nChairs tucked in neatly.\nDismissed in silence.")
    style = tmp_path / "exit.pptx"
    prs.save(style)
    out = tmp_path / "o.pptx"
    build_deck(style, [SlideContent(page=1, title="Exit", role="exit", bullets=["Something the AI wrote"])], {}, out)
    text = " ".join(sh.text_frame.text for sh in Presentation(str(out)).slides[0].shapes if sh.has_text_frame)
    assert "Lesson Exit Routines" in text and "Chairs tucked in neatly." in text and "AI wrote" not in text


def test_empty_placeholders_are_not_left_on_new_slides(tmp_path):
    prs = Presentation()  # the default "Title and Content" layout has two placeholders
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.placeholders[1].text_frame.text = "Index (noun): a sign or measure\nExample: the price index rose"
    box = s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(8), Inches(0.8)).text_frame
    box.text = "Vocabulary"
    style = tmp_path / "empty_title.pptx"
    prs.save(style)
    out = tmp_path / "o.pptx"
    build_deck(style, [SlideContent(page=1, title="Current", bullets=["Current (noun): rate of flow of charge"])], {}, out)
    slide = Presentation(str(out)).slides[0]
    assert all(sh.text_frame.text.strip() for sh in slide.shapes if sh.is_placeholder and sh.has_text_frame)


def test_numbered_lines_on_a_bulleted_slide_lose_the_bullet(tmp_path):
    out = tmp_path / "n.pptx"
    build_deck(lesson_deck(tmp_path), [SlideContent(page=1, title="Mini-whiteboard quiz", sample=3, bullets=[
        "1. Which meter measures current?", "2. What is the unit of potential difference?"])], {}, out)
    slide = Presentation(str(out)).slides[0]
    body = next(sh for sh in slide.shapes if sh.has_text_frame and "Which meter" in sh.text_frame.text)
    for p in body.text_frame.paragraphs:
        ppr = p._p.find("{http://schemas.openxmlformats.org/drawingml/2006/main}pPr")
        assert ppr is not None and ppr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}buNone") is not None


def test_long_lo_is_shrunk_to_its_strip(tmp_path):
    from tests.test_whole_lesson import _labelled_style
    out = tmp_path / "lo.pptx"
    long_lo = ("How do current, potential difference and resistance work in circuits, "
               "and how is mains electricity used safely at home?")
    build_deck(_labelled_style(tmp_path), [SlideContent(page=1, title="Circuits", bullets=["a"], sample=1)], {}, out,
               lesson_labels={"lo": long_lo})
    shape = next(sh for sh in Presentation(str(out)).slides[0].shapes if sh.has_text_frame and sh.text_frame.text.startswith("LO:"))
    sizes = [r.font.size.pt for p in shape.text_frame.paragraphs for r in p.runs if r.font.size]
    assert sizes and max(sizes) < 10  # her 10pt line got smaller to fit
