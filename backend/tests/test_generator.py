import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.generator import build_deck
from app.pptx_analysis import analyze_presentation
from app.schemas import SlideContent

FIX = Path(__file__).parent / "fixtures"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def _img(path, color, size=(800, 500), text=""):
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).text((20, 20), text, fill="white")
    im.save(path)
    return path


def _tb(slide, x, y, w, h, text, size, color="FFFFFF", bold=False):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = box.text_frame.paragraphs[0] if i == 0 else box.text_frame.add_paragraph()
        r = p.add_run(); r.text = line
        r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = RGBColor.from_string(color)
    return box


def _slide_count_in_zip(path):
    with zipfile.ZipFile(path) as z:
        return len([n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")])


def test_background_photo_and_logo_are_kept(tmp_path):
    """Full-bleed background + a logo on every slide are style, not content."""
    bgp = _img(tmp_path / "bg.png", "#223355", (1600, 900), "BACKGROUND")
    logo = _img(tmp_path / "logo.png", "#cc3344", (300, 300), "LOGO")
    photo = _img(tmp_path / "photo.png", "#338844", (900, 600), "SAMPLE PHOTO")

    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    for i in range(3):
        s = prs.slides.add_slide(blank)
        s.shapes.add_picture(str(bgp), 0, 0, prs.slide_width, prs.slide_height)
        s.shapes.add_picture(str(logo), Inches(12.2), Inches(0.2), Inches(0.9), Inches(0.9))
        _tb(s, 0.8, 0.5, 11, 1, f"Sample title {i}", 40, bold=True)
        _tb(s, 0.8, 1.8, 5.5 if i == 2 else 11, 4.5, ["First sample point", "Second sample point"], 24)
        if i == 2:
            s.shapes.add_picture(str(photo), Inches(7), Inches(1.8), Inches(5.5), Inches(3.6))
    style = tmp_path / "style.pptx"; prs.save(style)

    infos = analyze_presentation(Presentation(str(style)))
    assert [i.kind for i in infos] == ["title", "content", "image"] or [i.kind for i in infos][1:] == ["content", "image"], [i.kind for i in infos]
    assert all(len(i.picture_ids) <= 1 for i in infos)  # bg and logo not counted

    new_photo = _img(tmp_path / "new.png", "#ddaa00", (700, 700), "NEW")
    contents = [
        SlideContent(page=1, kind="content", title="Plain slide", bullets=["One", "Two"], notes="Say hello."),
        SlideContent(page=2, kind="image", title="With picture", bullets=["Look at this"], notes="Discuss the picture."),
    ]
    out = OUT / "bg_logo.pptx"
    warnings = build_deck(style, contents, {2: new_photo}, out)
    result = Presentation(str(out))
    assert len(result.slides) == 2 and _slide_count_in_zip(out) == 2
    for slide in result.slides:
        pics = [s for s in slide.shapes if s.shape_type == 13]
        assert len(pics) >= 2, "background + logo must survive"  # bg, logo (+ new photo on page 2)
    assert len([s for s in result.slides[1].shapes if s.shape_type == 13]) == 3
    assert result.slides[0].notes_slide.notes_text_frame.text == "Say hello."
    assert "SAMPLE" not in "\n".join(sh.text_frame.text for sl in result.slides for sh in sl.shapes if sh.has_text_frame)


def test_layout_only_deck(tmp_path):
    prs = Presentation()  # zero slides, only layouts
    style = tmp_path / "layouts.pptx"; prs.save(style)
    contents = [
        SlideContent(page=1, kind="title", title="Hello", subtitle="Sub"),
        SlideContent(page=2, kind="content", title="Body", bullets=["a", "b"]),
        SlideContent(page=3, kind="section", title="Break"),
    ]
    out = OUT / "layout_only.pptx"
    build_deck(style, contents, {}, out)
    r = Presentation(str(out))
    assert len(r.slides) == 3
    assert r.slides[1].shapes.title.text_frame.text == "Body"


def test_single_slide_deck_and_image_fallback(tmp_path):
    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    _tb(s, 1, 0.5, 11, 1, "Only slide", 40, "000000", True)
    _tb(s, 1, 2, 11, 4, ["Point A", "Point B", "Point C"], 24, "000000")
    style = tmp_path / "one.pptx"; prs.save(style)
    photo = _img(tmp_path / "p.png", "#445566", (600, 900), "TALL")
    contents = [
        SlideContent(page=1, kind="title", title="Intro", subtitle="Welcome"),
        SlideContent(page=2, kind="image", title="Picture", bullets=["Tall image"]),
    ]
    out = OUT / "single.pptx"
    warnings = build_deck(style, contents, {2: photo}, out)
    r = Presentation(str(out))
    assert len(r.slides) == 2
    pic = [sh for sh in r.slides[1].shapes if sh.shape_type == 13][0]
    # tall image must stay inside the slide and keep its aspect ratio
    assert pic.top >= 0 and pic.top + pic.height <= prs.slide_height
    assert pic.left + pic.width <= prs.slide_width
    assert abs(pic.width / pic.height - 600 / 900) < 0.02


def _sizes(path):
    r = Presentation(str(path))
    return [run.font.size.pt for sh in r.slides[0].shapes if sh.has_text_frame
            for p in sh.text_frame.paragraphs for run in p.runs if run.font.size]


def test_moderate_overflow_is_shrunk_without_warning():
    bullets = [f"A fairly long bullet point number {i} that wraps onto a second line when the font is large" for i in range(8)]
    out = OUT / "shrunk.pptx"
    warnings = build_deck(FIX / "biology_dark.pptx", [SlideContent(page=1, kind="content", title="Shrinking", bullets=bullets)], {}, out)
    assert not warnings, warnings
    assert min(_sizes(out)) < 26  # body was 26pt in the sample
    assert min(_sizes(out)) >= 14


def test_impossible_overflow_is_flagged():
    bullets = ["This bullet is intentionally very long. " * 6 for _ in range(12)]
    out = OUT / "overflow.pptx"
    warnings = build_deck(FIX / "biology_dark.pptx", [SlideContent(page=1, kind="content", title="Too much", bullets=bullets)], {}, out)
    assert any("overflow" in w for w in warnings), warnings
    assert min(_sizes(out)) >= 14


def test_sections_ext_removed(tmp_path):
    """Decks with PowerPoint sections must not keep stale slide ids (PowerPoint would 'repair' them)."""
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1]); s.shapes.title.text = "T"; s.placeholders[1].text = "B"
    sid = prs.slides._sldIdLst[0].get("id")
    ext_xml = (
        '<p:extLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:ext uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}">'
        '<p14:sectionLst xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">'
        f'<p14:section name="Sec" id="{{11111111-1111-1111-1111-111111111111}}"><p14:sldIdLst><p14:sldId id="{sid}"/></p14:sldIdLst></p14:section>'
        "</p14:sectionLst></p:ext></p:extLst>"
    )
    prs._element.append(etree.fromstring(ext_xml))
    style = tmp_path / "sections.pptx"; prs.save(style)
    out = OUT / "sections.pptx"
    build_deck(style, [SlideContent(page=1, kind="content", title="New", bullets=["x"])], {}, out)
    with zipfile.ZipFile(out) as z:
        assert b"sectionLst" not in z.read("ppt/presentation.xml")


def _runs(shape):
    return [r for p in shape.text_frame.paragraphs for r in p.runs]


def test_teacher_formatting_is_applied_per_word(tmp_path):
    """Formatted runs land in the pptx with valid <a:rPr> child order; unset fields keep the template."""
    from app.schemas import TextRun

    title = [TextRun(text="Solving "), TextRun(text="Quadratics", bold=True, color="#C00000", font="Georgia", size=44)]
    body = [
        [TextRun(text="Use the "), TextRun(text="formula", italic=True, underline=True, highlight="FFFF00")],
        [TextRun(text="Check", bold=False), TextRun(text=" your answer")],
    ]
    content = SlideContent(page=1, kind="content", title="x", title_runs=title, body_runs=body,
                           text_align="center", text_anchor="middle")
    out = tmp_path / "rich.pptx"
    build_deck(FIX / "biology_dark.pptx", [content], {}, out)
    slide = Presentation(str(out)).slides[0]
    t_shape, b_shape = (next(s for s in slide.shapes if s.has_text_frame and s.text_frame.text.startswith(p)) for p in ("Solving", "• Use"))

    plain, strong = _runs(t_shape)
    assert strong.text == "Quadratics" and strong.font.bold and strong.font.size.pt == 44
    assert str(strong.font.color.rgb) == "C00000" and strong.font.name == "Georgia"
    assert str(plain.font.color.rgb) == "F4D35E", "unset runs keep the template colour"
    assert plain.font.name == "Georgia" and plain.font.size.pt == 40, "unset runs keep the template font and size"

    use, formula, check, rest = _runs(b_shape)
    assert use.text == "• Use the ", "the template's typed bullet is kept"
    assert formula.font.italic and formula.font.underline
    rpr = formula._r.find(qn("a:rPr"))
    assert rpr.find(qn("a:highlight")).find(qn("a:srgbClr")).get("val") == "FFFF00"
    order = [c.tag.split("}")[1] for c in rpr]
    assert order.index("solidFill") < order.index("highlight") < order.index("latin"), order
    assert check._r.find(qn("a:rPr")).get("b") == "0"
    assert all(p.alignment == 2 for p in b_shape.text_frame.paragraphs)  # PP_ALIGN.CENTER
    assert b_shape.text_frame._txBody.find(qn("a:bodyPr")).get("anchor") == "ctr"


def _pic_boxes(slide):
    return [(s.left, s.top, s.width, s.height) for s in slide.shapes if s.shape_type == 13]


def test_image_positions(tmp_path):
    """Left/right/top split the sample's content area between picture and body; large moves
    bullets to the notes; none drops the picture."""
    photo = _img(tmp_path / "photo.png", "#2255aa", (800, 600), "PHOTO")
    # A sample image slide whose picture and text are split by a divider line.
    prs = Presentation(str(FIX / "biology_dark.pptx"))
    prs.slides[2].shapes.add_connector(1, Inches(6.7), Inches(1.9), Inches(6.7), Inches(6.4))
    style = tmp_path / "divided.pptx"; prs.save(style)
    base = dict(kind="image", title="Look closely", bullets=["Label the parts", "Explain each one"])
    contents = [
        SlideContent(page=n, image_position=pos, **base)
        for n, pos in enumerate(["left", "right", "top", "large", "none"], 1)
    ]
    out = tmp_path / "positions.pptx"
    warnings = build_deck(style, contents, {n: photo for n in range(1, 6)}, out)
    left, right, top, large, none = Presentation(str(out)).slides
    assert not any(s.shape_type == MSO_SHAPE_TYPE.LINE or s._element.tag.endswith("cxnSp") for s in left.shapes), "sample divider removed"

    def body(slide):
        return next(s for s in slide.shapes if s.has_text_frame and "Label the parts" in s.text_frame.text)

    (pic,) = _pic_boxes(left)
    assert pic[0] + pic[2] <= body(left).left, "picture left of the text"
    (pic,) = _pic_boxes(right)
    assert body(right).left + body(right).width <= pic[0], "picture right of the text"
    (pic,) = _pic_boxes(top)
    assert pic[1] + pic[3] <= body(top).top, "picture above the text"
    (pic,) = _pic_boxes(large)
    assert "Label the parts" in large.notes_slide.notes_text_frame.text
    assert not any(s.has_text_frame and "Label the parts" in s.text_frame.text for s in large.shapes)
    assert any("speaker notes" in w for w in warnings)
    assert _pic_boxes(none) == [], "no picture, and the sample's own picture is gone too"


def _all_text(slide):
    texts = []

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                walk(sh.shapes)
            if sh.has_text_frame:
                texts.append(sh.text_frame.text)
            if getattr(sh, "has_table", False):
                texts.extend(c.text for row in sh.table.rows for c in row.cells)

    walk(slide.shapes)
    return "\n".join(texts)


def test_no_sample_text_left_behind():
    """Small labels, grouped text and tables on a sample slide are content, not style;
    a footer repeated on every sample slide is style and stays."""
    infos = analyze_presentation(Presentation(str(FIX / "leftovers.pptx")))
    assert [i.kind for i in infos][1:] == ["content", "content"], [i.kind for i in infos]

    contents = [
        SlideContent(page=n, kind="content", title=f"New title {n}", bullets=[f"New point {n}a", f"New point {n}b"])
        for n in range(1, 7)
    ]
    out = OUT / "leftovers.pptx"
    build_deck(FIX / "leftovers.pptx", contents, {}, out)
    result = Presentation(str(out))
    assert len(result.slides) == 6
    for n, slide in enumerate(result.slides, 1):
        text = _all_text(slide)
        assert "OLD" not in text, f"slide {n} kept sample text:\n{text}"
        assert f"New title {n}" in text and f"New point {n}b" in text
        assert "Oak Hill School" in text, f"slide {n} lost the repeated footer"


def test_designed_template_keeps_cover_art_off_content_slides():
    """Cover designs (layouts dressed with logos) only make covers; content slides come from
    the cleanest samples and lose the cards, bars and icons that framed sample content."""
    infos = analyze_presentation(Presentation(str(FIX / "dressed.pptx")))
    assert [i.kind for i in infos] == ["title", "content", "content", "content", "title"]

    contents = [SlideContent(page=0, kind="title", title="Quadratic Equations", subtitle="Year 10")]
    contents += [SlideContent(page=n, kind="content", title=f"New title {n}", bullets=[f"Point {n}"]) for n in range(1, 5)]
    out = OUT / "dressed.pptx"
    build_deck(FIX / "dressed.pptx", contents, {}, out)
    result = Presentation(str(out))

    cover, *slides = result.slides
    assert cover.slide_layout.name == "Title Only", "the cover keeps its dressed design"
    for n, slide in enumerate(slides, 1):
        assert slide.slide_layout.name == "Blank", f"slide {n} reused a cover or card-art layout"
        text = _all_text(slide)
        assert "OLD" not in text and f"New title {n}" in text and "Private & Confidential" in text
        leftovers = [sh.shape_type for sh in slide.shapes if sh.shape_type in (MSO_SHAPE_TYPE.AUTO_SHAPE, MSO_SHAPE_TYPE.PICTURE)]
        assert not leftovers, f"slide {n} kept sample decoration: {leftovers}"


def test_very_long_line_still_builds(tmp_path):
    """A paragraph of notes with no sentence breaks becomes one long bullet: warn, don't crash."""
    out = tmp_path / "long.pptx"
    warnings = build_deck(FIX / "biology_dark.pptx", [SlideContent(page=1, title="Long", bullets=["word " * 600])], {}, out)
    assert any("overflow" in w for w in warnings)
    slide = Presentation(str(out)).slides[0]
    assert any("word word" in sh.text_frame.text for sh in slide.shapes if sh.has_text_frame)
