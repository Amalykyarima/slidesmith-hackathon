"""Recognises the routine slides teachers repeat every lesson.

Many schools build every lesson from the same blocks: a retrieval starter,
a vocabulary slide, "Turn and Talk", "I do / We do / You do", homework and a
stretch task. A teacher's sample deck usually contains one (or many) of each.
Matching a requested page to the sample with the *same role* gives far better
results than matching by layout alone.
"""
from __future__ import annotations

import re

# Checked in order: the first pattern that matches wins. "I do" is last because
# teaching slides often carry an "I do" badge next to a more specific heading.
ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("retrieval", re.compile(r"\bretrieval\b|\bdo now\b|\bstarter\b")),
    ("vocabulary", re.compile(r"\bvocab(ulary)?\b")),
    ("turn_and_talk", re.compile(r"\bturn and talk\b|\bthink,? pair,? share\b")),
    ("we_do", re.compile(r"\bmwb\b|\bmini[- ]?whiteboards?\b|\bwe do\b")),
    ("you_do", re.compile(r"\bindependent (task|practice|work)\b|\byou do\b")),
    ("homework", re.compile(r"\bhome ?learning\b|\bhomework\b")),
    ("stretch", re.compile(r"\bsuper stretch\b|\bstretch\b")),
    ("exit", re.compile(r"\bexit (routine|routines|ticket)\b")),
    ("i_do", re.compile(r"\bi do\b")),
]

ROLES = [name for name, _ in ROLE_PATTERNS]

# Small labels that belong to one lesson and must never be copied into another.
LESSON_LABEL = re.compile(r"^\s*(lo|l\.o\.|learning objectives?|keywords?|key words)\s*[:\-]", re.I)

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def _norm(text: str) -> str:
    return " ".join(text.translate(_QUOTES).lower().split())


def role_of(text: str) -> str | None:
    """The routine role named in `text`, or None for an ordinary teaching slide."""
    t = _norm(text or "")
    if not t:
        return None
    for name, pattern in ROLE_PATTERNS:
        if pattern.search(t):
            return name
    return None


def is_lesson_label(text: str) -> bool:
    return bool(LESSON_LABEL.match(text or ""))


# A vocabulary definition: "essential (noun): absolutely necessary", "impair (verb): to weaken…"
_DEFINITION = re.compile(
    r"^\s*[A-Za-z][\w'\-]*(\s+[\w'\-]+)?\s*\((noun|verb|adjective|adverb|adj|n|v)\.?\)\s*[:\-]", re.I
)
_LABEL = re.compile(r"^\s*([A-Za-z][A-Za-z \-]{1,28}?)\s*:")


def slot_key(text: str) -> str | None:
    """What a labelled box (or line) is for: "definition", or its label such as
    "application task" or "challenge". None for plain text."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    if not first:
        return None
    if _DEFINITION.match(first):
        return "definition"
    m = _LABEL.match(first)
    return " ".join(m.group(1).lower().split()) if m else None
