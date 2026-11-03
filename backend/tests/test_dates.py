"""Lesson dates: the sample's dates become the lesson's, in the teacher's own format."""
import datetime as dt

import pytest
from pptx import Presentation
from pptx.util import Inches

from app.dates import find_dates, next_school_day, rewrite
from app.generator import build_deck, refresh_dates
from app.schemas import SlideContent
from tests.test_style_fidelity import lesson_deck

TODAY = dt.date(2026, 11, 3)
LESSON = dt.date(2026, 11, 4)  # a Wednesday


@pytest.mark.parametrize("old,new", [
    ("Nutrients          24th Sep 2026", "Nutrients          4th Nov 2026"),
    ("Wednesday, 06 August 2025", "Wednesday, 04 November 2026"),
    ("TUESDAY 14 OCT 2025", "WEDNESDAY 4 NOV 2026"),
    ("Wed 6th Aug", "Wed 4th Nov"),
    ("Thursday 2nd October", "Wednesday 4th November"),
    ("Monday, September 1, 2025", "Wednesday, November 4, 2026"),
    ("Aug 6th, 2026", "Nov 4th, 2026"),
    ("06/08/2025", "04/11/2026"),
    ("6.8.25", "4.11.26"),
    ("2025-08-06", "2026-11-04"),
])
def test_rewrites_in_the_same_format(old, new):
    assert rewrite(old, LESSON, TODAY) == new


@pytest.mark.parametrize("text", [
    "WW2 ended on 2 September 1945",  # history: far from now
    "Due 2 May",  # no year, weekday or ordinal: could be anything
    "Lesson 3 of 6", "12/2025", "Year 8", "Page 24 of 30",
])
def test_leaves_other_text_alone(text):
    assert find_dates(text, TODAY) == []


def test_ordinals():
    for day, want in [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"),
                      (13, "13th"), (21, "21st"), (22, "22nd"), (23, "23rd"), (31, "31st")]:
        assert rewrite("Mon 1st Sep", dt.date(2026, 12, day), TODAY).split()[1] == want


def test_next_school_day():
    assert next_school_day(dt.date(2026, 11, 3)) == dt.date(2026, 11, 4)  # Tue -> Wed
    assert next_school_day(dt.date(2026, 11, 6)) == dt.date(2026, 11, 9)  # Fri -> Mon
    assert next_school_day(dt.date(2026, 11, 7)) == dt.date(2026, 11, 9)  # Sat -> Mon


def test_date_split_over_runs_keeps_formatting():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    p = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text_frame.paragraphs[0]
    for text, bold in [("Date: ", False), ("24", True), ("th", True), (" Sep 2026", True)]:
        r = p.add_run()
        r.text, r.font.bold = text, bold
    assert refresh_dates(slide, LESSON) == 1
    assert p.runs[0].text == "Date: " and "".join(r.text for r in p.runs) == "Date: 4th Nov 2026"
    assert p.runs[1].font.bold


def test_deck_gets_the_lesson_date(tmp_path):
    out = tmp_path / "dated.pptx"
    build_deck(lesson_deck(tmp_path), [
        SlideContent(page=1, title="Alcohol", role="retrieval",
                     bullets=["Retrieval Practice:", "When did WW2 end? (2 September 1945)", "Test on 24th Sep 2026?"]),
    ], {}, out, lesson_date=LESSON)
    slide = Presentation(str(out)).slides[0]
    texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
    head = next(t for t in texts if t.startswith("Alcohol"))
    assert head.endswith("4th Nov 2026") and "    " in head  # her "Topic <gap> Date" layout, new date
    body = next(t for t in texts if "Retrieval Practice" in t)
    assert "2 September 1945" in body and "24th Sep 2026" in body  # lesson content is never changed
