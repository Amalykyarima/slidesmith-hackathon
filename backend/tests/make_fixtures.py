"""Creates sample 'teacher' decks for testing: python tests/make_fixtures.py"""
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

OUT = Path(__file__).parent / "fixtures"
OUT.mkdir(exist_ok=True)


def tb(slide, x, y, w, h, text, size, color, bold=False, font="Georgia", align=PP_ALIGN.LEFT, bullets=False):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = ("• " + line) if bullets else line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = font
        r.font.color.rgb = RGBColor.from_string(color)
        if bullets:
            p.space_after = Pt(8)
    return box


def bg(slide, hex_):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string(hex_)


def sample_image(path: Path):
    im = Image.new("RGB", (900, 600), "#F4A261")
    d = ImageDraw.Draw(im)
    d.ellipse((150, 100, 750, 500), fill="#2A9D8F", outline="#264653", width=8)
    d.ellipse((350, 220, 550, 380), fill="#E9C46A", outline="#264653", width=6)
    d.text((380, 285), "NUCLEUS", fill="#264653")
    im.save(path)


def textbox_deck():
    """Typical teacher deck: dark teal, Georgia, everything is a text box on a blank layout."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    BG, TITLE, BODY, ACC = "12343B", "F4D35E", "F7F7F2", "EE964B"

    s = prs.slides.add_slide(blank); bg(s, BG)
    tb(s, 1, 2.3, 11.3, 1.5, "Welcome to Biology", 54, TITLE, True)
    tb(s, 1, 4.0, 11.3, 0.8, "Mr. Adams  |  Year 9", 24, ACC, font="Calibri")

    s = prs.slides.add_slide(blank); bg(s, BG)
    tb(s, 0.8, 0.6, 11.7, 1.0, "Photosynthesis Basics", 40, TITLE, True)
    tb(s, 0.8, 1.9, 11.7, 4.6, ["Plants make food using sunlight", "Happens in the chloroplasts", "Needs water and carbon dioxide", "Produces glucose and oxygen"], 26, BODY, font="Calibri", bullets=True)

    s = prs.slides.add_slide(blank); bg(s, BG)
    tb(s, 0.8, 0.6, 11.7, 1.0, "Look at the Diagram", 40, TITLE, True)
    tb(s, 0.8, 1.9, 5.6, 4.6, ["Label the parts", "Explain each function"], 26, BODY, font="Calibri", bullets=True)
    img = OUT / "sample_diagram.png"; sample_image(img)
    s.shapes.add_picture(str(img), Inches(7.0), Inches(1.9), Inches(5.5), Inches(3.67))

    s = prs.slides.add_slide(blank); bg(s, ACC)
    tb(s, 1, 3.0, 11.3, 1.5, "Key Terms", 54, "12343B", True, align=PP_ALIGN.CENTER)

    prs.save(OUT / "biology_dark.pptx")


def placeholder_deck():
    """Deck that uses real layouts/placeholders (python-pptx default template, widescreen)."""
    prs = Presentation()  # keep the template's native 4:3 so placeholders line up
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Maths Starter"
    s.placeholders[1].text = "Year 8  |  Ms. Okafor"
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Solving Equations"
    tf = s.placeholders[1].text_frame
    tf.text = "Do the same to both sides"
    for t in ("Isolate the unknown", "Check your answer"):
        tf.add_paragraph().text = t
    prs.save(OUT / "maths_layouts.pptx")


if __name__ == "__main__":
    textbox_deck()
    placeholder_deck()
    print("fixtures written to", OUT)
