"""Generated slides should look like the teacher's own: footer bars stay, labelled
boxes (definition banner, application task) are filled separately, "Topic  Date"
headings keep their layout, and long text uses free space before shrinking."""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from app.generator import _estimate_height, _split_title, _wrapped_lines, build_deck
from app.pptx_analysis import analyze_presentation
from app.roles import slot_key
from app.schemas import SlideContent

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def _tb(slide, x, y, w, h, lines, size, underline=False):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    for i, line in enumerate(lines if isinstance(lines, list) else [lines]):
        p = box.text_frame.paragraphs[0] if i == 0 else box.text_frame.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.underline = underline
        r.font.color.rgb = RGBColor(0, 0, 0)
    return box


def lesson_deck(tmp_path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    blank = prs.slide_layouts[6]

    # Retrieval: "Topic <spaces> Date" header made of three runs (spaces not underlined),
    # a question box that runs behind a full-width yellow footer bar.
    s = prs.slides.add_slide(blank)
    head = _tb(s, 0.1, 0.0, 9.7, 0.5, "Nutrients", 27, underline=True)
    p = head.text_frame.paragraphs[0]
    gap = p.add_run(); gap.text = " " * 40; gap.font.size = Pt(27)
    date = p.add_run(); date.text = "24th Sep 2026"; date.font.size = Pt(27); date.font.underline = True
    _tb(s, 0.1, 0.7, 8.1, 4.8, ["Retrieval Practice:", "Which organ system breaks food down?",
                                "How would you define a healthy diet?"], 28)
    bar = s.shapes.add_shape(1, Inches(0), Inches(5.1), Inches(10), Inches(0.52))
    bar.fill.solid(); bar.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0x33)
    bar.text_frame.text = "Tier 3 - "

    # Vocabulary: heading, definition banner, examples body, application task box.
    s = prs.slides.add_slide(blank)
    _tb(s, 0.3, 0.2, 8.0, 0.6, "Tier 2 Vocabulary", 33)
    _tb(s, 1.2, 0.9, 7.0, 0.6, "Essential (noun): absolutely necessary", 24)
    _tb(s, 1.2, 1.6, 7.0, 2.4, ["Examples:", "Science: Protein is essential for growth and repair"], 26)
    _tb(s, 1.2, 4.2, 7.0, 0.8, "Application task: Write a grammatically-correct sentence using this word", 18)

    # Independent task: short box with lots of empty slide below it.
    s = prs.slides.add_slide(blank)
    _tb(s, 0.5, 0.2, 9.0, 0.8, "Independent Practice", 44)
    _tb(s, 0.5, 1.2, 8.8, 1.6, ["List the seven nutrients.", "Where can we find nutrition labels?"], 30)

    path = tmp_path / "lesson_style.pptx"
    prs.save(path)
    return path


def test_slot_keys():
    assert slot_key("impair (verb): to weaken or damage something") == "definition"
    assert slot_key("Essential (noun): absolutely necessary") == "definition"
    assert slot_key("Application task: Write a sentence") == "application task"
    assert slot_key("Challenge: Explain why") == "challenge"
    assert slot_key("What is a drug? (1)") is None
    assert slot_key("Units = % alcohol × volume (ml) ÷ 1000") is None


def test_title_split_and_wrapping():
    assert _split_title("Alcohol   5th Nov 2026") == ("Alcohol", "5th Nov 2026")
    assert _split_title("Alcohol | 5th Nov 2026") == ("Alcohol", "5th Nov 2026")
    assert _split_title("Alcohol 5th Nov 2026") == ("Alcohol", "5th Nov 2026")
    assert _split_title("Short-term effects") is None
    assert _wrapped_lines("one two three four", 10) == 2  # "one two" / "three four"
    assert _wrapped_lines("one two three four", 9) == 3
    assert _wrapped_lines("", 10) == 1
    # Word wrapping shouldn't count more lines than a naive character split would.
    text = "Explain why drinking alcohol before driving is dangerous. (2)"
    assert _estimate_height([text], 20, 400) <= 2 * 20 * 1.2


def test_analysis_keeps_bars_and_finds_slots(tmp_path):
    infos = analyze_presentation(Presentation(str(lesson_deck(tmp_path))))
    retrieval, vocab, _ = infos
    assert retrieval.stale_ids == [] and retrieval.clutter == 0  # the yellow bar is style
    assert sorted(vocab.slots.values()) == ["application task", "definition"]


def test_generated_slides_follow_the_style(tmp_path):
    style = lesson_deck(tmp_path)
    contents = [
        SlideContent(page=1, title="Alcohol   5th Nov 2026", role="retrieval",
                     bullets=["Retrieval Practice:", *[f"Question number {n} about alcohol and drugs? (2)" for n in range(1, 7)]]),
        SlideContent(page=2, title="Tier 2 Vocabulary", bullets=[
            "impair (verb): to weaken or damage something so it works less well.",
            "General: Lack of sleep can impair your concentration.",
            "Scientific: Alcohol impairs the nervous system.",
            "Application task: Write a grammatically-correct sentence using this word.",
        ]),
        SlideContent(page=3, title="Independent Practice", bullets=[
            f"Explain in detail a long question number {n} about the effects of alcohol. (2)" for n in range(1, 7)
        ]),
    ]
    out = OUT / "fidelity.pptx"
    build_deck(style, contents, {}, out)
    prs = Presentation(str(out))
    retrieval, vocab, task = prs.slides

    # Footer bar kept; the question box now stops above it.
    bar = next(sh for sh in retrieval.shapes if sh.has_text_frame and sh.text_frame.text.startswith("Tier 3"))
    body = next(sh for sh in retrieval.shapes if sh.has_text_frame and "Retrieval Practice" in sh.text_frame.text)
    assert body.top + body.height <= bar.top

    # Header keeps "Topic <gap> Date": three runs, the gap not underlined, same overall length.
    head = next(sh for sh in retrieval.shapes if sh.has_text_frame and sh.text_frame.text.startswith("Alcohol"))
    runs = head.text_frame.paragraphs[0].runs
    assert [r.text.strip() for r in runs] == ["Alcohol", "", "5th Nov 2026"]
    assert runs[0].font.underline and not runs[1].font.underline and runs[2].font.underline
    assert len(head.text_frame.text) == len("Nutrients" + " " * 40 + "24th Sep 2026")

    # Definition into the banner, application task into its box, the rest in the body.
    texts = {sh.text_frame.text for sh in vocab.shapes if sh.has_text_frame}
    assert "impair (verb): to weaken or damage something so it works less well." in texts
    assert "Application task: Write a grammatically-correct sentence using this word." in texts
    assert "General: Lack of sleep can impair your concentration.\nScientific: Alcohol impairs the nervous system." in texts

    # Long list: the box grew into the empty space below instead of shrinking to the minimum.
    body = next(sh for sh in task.shapes if sh.has_text_frame and "question number 1" in sh.text_frame.text)
    assert body.height > Inches(1.6)
    sizes = {r.font.size.pt for p in body.text_frame.paragraphs for r in p.runs if r.font.size}
    assert min(sizes) > 18
