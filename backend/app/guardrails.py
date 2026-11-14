"""Rule-based guardrails: the checks that must never depend on a model.

They run twice:
- on the way IN (before anything reaches the AI): personal data is redacted and prompt-injection
  attempts in pasted material are neutralised;
- on the way OUT (after the agents have written the slides): reading level, slide density and
  personal data are checked again, and anything worrying is flagged for the teacher.

Severity: "block" = must be fixed or removed before the deck is built; "check" = the teacher should
look; "info" = for her information. Any "block" or "check" sends the run to human review.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .levels import Level

# --------------------------------------------------------------------------- personal data
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
UK_PHONE = re.compile(r"(?<!\d)(?:\+44\s?7\d{3}|07\d{3})\s?\d{3}\s?\d{3}(?!\d)|(?<!\d)(?:\+44\s?|0)(?:1|2)\d{2,3}\s?\d{3}\s?\d{3,4}(?!\d)")
# Unique Pupil Number: a letter then 12 digits (England/Wales).
UPN = re.compile(r"\b[A-HJ-NP-TV-Z]\d{12}\b")
POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
DOB = re.compile(r"\b(?:dob|d\.o\.b\.?|date of birth)\s*[:\-]?\s*\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b", re.I)

_PII = [("email address", EMAIL), ("phone number", UK_PHONE), ("pupil number (UPN)", UPN),
        ("postcode", POSTCODE), ("date of birth", DOB)]

# --------------------------------------------------------------------------- prompt injection
INJECTION = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)"
    r"|you are now\b|system prompt|\bjailbreak\b|developer mode",
    re.I,
)


@dataclass
class Flag:
    page: int            # 0 = the whole lesson
    severity: str        # block | check | info
    kind: str            # personal_data | reading_level | density | injection | accuracy | age_fit | safeguarding | inclusion
    message: str
    source: str = "rules"  # rules | reviewer
    suggestion: str = ""

    def dict(self) -> dict:
        return asdict(self)


def find_personal_data(text: str) -> list[str]:
    return [label for label, rx in _PII if rx.search(text or "")]


def redact(text: str) -> tuple[str, list[str]]:
    """Replace personal data with placeholders. Returns (clean text, kinds found)."""
    found: list[str] = []
    out = text or ""
    for label, rx in _PII:
        out, n = rx.subn(f"[{label} removed]", out)
        if n:
            found.append(label)
    return out, found


def neutralise_injection(text: str) -> tuple[str, bool]:
    """Pasted worksheets or web text sometimes carry 'ignore previous instructions'. Quote it out."""
    if not INJECTION.search(text or ""):
        return text, False
    return INJECTION.sub(lambda m: f"«{m.group(0)}»", text), True


# --------------------------------------------------------------------------- readability
_VOWELS = re.compile(r"[aeiouy]+")


def _syllables(word: str) -> int:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(_VOWELS.findall(w)))


def grade_level(text: str) -> float | None:
    """Flesch-Kincaid grade. Each bullet counts as a sentence (slides rarely use full stops)."""
    sentences = [s for s in re.split(r"[.!?\n]+", text or "") if re.search(r"[A-Za-z]", s)]
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text or "")
    if len(words) < 8 or not sentences:
        return None  # too little text to judge
    syll = sum(_syllables(w) for w in words)
    return round(0.39 * (len(words) / len(sentences)) + 11.8 * (syll / len(words)) - 15.59, 1)


def slide_text(slide: dict) -> str:
    return "\n".join([slide.get("title", ""), slide.get("subtitle", ""), *slide.get("bullets", [])])


# --------------------------------------------------------------------------- output checks
def check_slides(slides: list[dict], level: Level) -> list[Flag]:
    flags: list[Flag] = []
    for s in slides:
        page = s.get("page", 0)
        text = slide_text(s)
        pii = find_personal_data(text + "\n" + (s.get("notes") or ""))
        if pii:
            flags.append(Flag(page, "block", "personal_data",
                              f"This slide contains what looks like a {', '.join(pii)}. Pupil data must never go on slides.",
                              suggestion="Remove it, or replace it with a placeholder."))
        if INJECTION.search(text):
            flags.append(Flag(page, "check", "injection",
                              "This slide repeats an instruction aimed at the AI (\"ignore previous instructions\").",
                              suggestion="Delete that line."))
        grade = grade_level("\n".join(s.get("bullets", [])))
        if grade is not None and grade > level.max_grade + 1.5:
            flags.append(Flag(page, "check", "reading_level",
                              f"Reading level is about grade {grade:g}, above the {level.label} target "
                              f"(grade {level.max_grade:g} or below).",
                              suggestion="Shorter sentences and simpler words."))
        bullets = s.get("bullets", [])
        if len(bullets) > level.max_bullets + 2:
            flags.append(Flag(page, "info", "density",
                              f"{len(bullets)} bullets: dense for {level.label} (aim for {level.max_bullets})."))
        long = [b for b in bullets if len(b.split()) > level.max_words_per_bullet * 2]
        if long:
            flags.append(Flag(page, "info", "density",
                              f"{len(long)} bullet(s) over {level.max_words_per_bullet * 2} words."))
    return flags


def needs_review(flags: list[Flag | dict]) -> bool:
    sev = [(f.severity if isinstance(f, Flag) else f.get("severity")) for f in flags]
    return any(s in ("block", "check") for s in sev)
