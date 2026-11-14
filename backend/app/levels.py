"""One product for every stage of education.

The teacher picks a level. It changes who the AI writes for, how dense a slide may be,
how strict the reviewer is and how much scaffolding the SEN adapter adds. Nothing here
touches the teacher's style: that still comes only from her own slides.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    key: str
    label: str
    audience: str            # who the slides are for, in the AI's words
    reading_age: str         # shown to the teacher
    max_grade: float         # highest Flesch-Kincaid grade before the reviewer flags a slide
    max_words_per_bullet: int
    max_bullets: int
    guidance: str            # extra writing rules for the planner


LEVELS: dict[str, Level] = {
    "primary": Level(
        key="primary",
        label="Primary (KS1-KS2)",
        audience="primary school pupils aged 5-11",
        reading_age="7-10",
        max_grade=5.0,
        max_words_per_bullet=10,
        max_bullets=4,
        guidance=(
            "Write for primary pupils: very short sentences, everyday words, one idea per bullet. "
            "Explain any subject word the first time it appears. Use a friendly, encouraging voice and "
            "concrete examples from a child's life. Questions should be answerable in a few words."
        ),
    ),
    "secondary": Level(
        key="secondary",
        label="Secondary (KS3-KS4)",
        audience="secondary school students aged 11-16",
        reading_age="11-14",
        max_grade=9.0,
        max_words_per_bullet=14,
        max_bullets=6,
        guidance=(
            "Write for secondary students: clear and exam-aware. Use correct subject terminology and "
            "define key terms. Questions can build from recall to explanation."
        ),
    ),
    "university": Level(
        key="university",
        label="University / FE",
        audience="university or further-education students",
        reading_age="16+",
        max_grade=14.0,
        max_words_per_bullet=20,
        max_bullets=7,
        guidance=(
            "Write for university students: precise, discipline-specific language and concise lecture-slide "
            "bullets. Prompts can ask for analysis, evaluation and application. Do not invent citations: "
            "if a source would help, say what kind of source to look up instead of naming one."
        ),
    ),
}

DEFAULT_LEVEL = "secondary"


def get(key: str | None) -> Level:
    return LEVELS.get((key or "").strip().lower(), LEVELS[DEFAULT_LEVEL])


def public() -> list[dict]:
    return [{"key": l.key, "label": l.label, "reading_age": l.reading_age} for l in LEVELS.values()]
