"""Lesson dates on slides.

Sample slides carry the date of the lesson they were made for ("24th Sep 2026",
"Wednesday, 06 August 2025", "06/08/25"). On a new slide that date must be the new
lesson's, written exactly the way the teacher writes dates. Only text copied from the
sample is changed: dates in the lesson content (history!) are never touched.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Callable

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_WD = r"(?P<wd>(?:mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun)(?:day|nesday|sday|rsday|urday)?\.?)"
_MON = r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?P<mdot>\.)?"
_DAY = r"(?P<day>\d{1,2})(?P<ord>st|nd|rd|th)?"
# "Wednesday, 06 August 2025" · "24th Sep 2026" · "Wed 6th of Aug" · "6 August, 2025"
_DAY_FIRST = re.compile(
    rf"\b(?:{_WD}(?P<s1>,?\s+))?{_DAY}(?P<of>\s+of)?(?P<s2>\s+){_MON}(?:(?P<s3>,?\s+)(?P<year>\d{{4}}|'?\d{{2}}))?\b",
    re.I,
)
# "Wednesday, August 6, 2025" · "Aug 6th 2026"
_MONTH_FIRST = re.compile(
    rf"\b(?:{_WD}(?P<s1>,?\s+))?{_MON}(?P<s2>\s+){_DAY}(?:(?P<s3>,?\s+)(?P<year>\d{{4}}))?\b",
    re.I,
)
# "06/08/2025" · "6.8.25" · "06-08-2025" (UK order: day first)
_NUMERIC = re.compile(r"\b(?P<day>\d{1,2})(?P<sep>[/.\-])(?P<mon>\d{1,2})(?P=sep)(?P<year>\d{4}|\d{2})\b")
# "2025-08-06"
_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<mon>\d{2})-(?P<day>\d{2})\b")


@dataclass
class Found:
    start: int
    end: int
    text: str
    write: Callable[[dt.date], str]  # the new date, written like this one


def _case(word: str, like: str) -> str:
    if like.isupper() and len(like) > 1:
        return word.upper()
    if like.islower():
        return word.lower()
    return word[:1].upper() + word[1:].lower()


def ordinal(n: int) -> str:
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _month_num(word: str) -> int:
    return [m[:3].lower() for m in MONTHS].index(word[:3].lower()) + 1


def _plausible_year(year: str | None, today: dt.date) -> bool:
    if not year:
        return True
    y = int(year.lstrip("'"))
    y = y + 2000 if y < 100 else y
    return today.year - 5 <= y <= today.year + 2  # a recent lesson, not a historical date


def _word_writer(m: re.Match) -> Callable[[dt.date], str]:
    g = m.groupdict()

    def weekday(d: dt.date) -> str:
        name = DAYS[d.weekday()]
        raw = g["wd"].rstrip(".")
        short = len(raw) <= 5 and not raw.lower().endswith("day")
        out = name[:3] if short and len(raw) == 3 else (name[: len(raw)] if short else name)
        return _case(out, raw) + ("." if g["wd"].endswith(".") else "")

    def month(d: dt.date) -> str:
        name = MONTHS[d.month - 1]
        raw = g["mon"]
        if len(raw) <= 4 and raw.lower() not in ("june", "july"):
            name = "Sept" if (raw.lower() == "sept" and d.month == 9) else name[:3]
        return _case(name, raw) + (g.get("mdot") or "")

    def day(d: dt.date) -> str:
        n = f"{d.day:02d}" if (g["day"].startswith("0") and len(g["day"]) == 2) else str(d.day)
        return n + (_case(ordinal(d.day), g["ord"]) if g["ord"] else "")

    def year(d: dt.date) -> str:
        y = g["year"]
        if len(y.lstrip("'")) == 2:
            return ("'" if y.startswith("'") else "") + f"{d.year % 100:02d}"
        return str(d.year)

    return weekday, month, day, year


def _write_day_first(m: re.Match) -> Callable[[dt.date], str]:
    weekday, month, day, year = _word_writer(m)
    g = m.groupdict()

    def write(d: dt.date) -> str:
        out = (weekday(d) + g["s1"]) if g["wd"] else ""
        out += day(d) + (g["of"] or "") + g["s2"] + month(d)
        return out + ((g["s3"] + year(d)) if g["year"] else "")

    return write


def _write_month_first(m: re.Match) -> Callable[[dt.date], str]:
    weekday, month, day, year = _word_writer(m)
    g = m.groupdict()

    def write(d: dt.date) -> str:
        out = (weekday(d) + g["s1"]) if g["wd"] else ""
        out += month(d) + g["s2"] + day(d)
        return out + ((g["s3"] + year(d)) if g["year"] else "")

    return write


def _write_numeric(m: re.Match) -> Callable[[dt.date], str]:
    g = m.groupdict()

    def part(n: int, like: str) -> str:
        return f"{n:02d}" if len(like) == 2 else str(n)

    def write(d: dt.date) -> str:
        y = str(d.year) if len(g["year"]) == 4 else f"{d.year % 100:02d}"
        return part(d.day, g["day"]) + g["sep"] + part(d.month, g["mon"]) + g["sep"] + y

    return write


def find_dates(text: str, today: dt.date | None = None) -> list[Found]:
    """Lesson-style dates in `text` (recent or upcoming, never historical ones)."""
    today = today or dt.date.today()
    found: list[Found] = []

    def free(a: int, b: int) -> bool:
        return all(b <= f.start or a >= f.end for f in found)

    for rx, writer in ((_DAY_FIRST, _write_day_first), (_MONTH_FIRST, _write_month_first)):
        for m in rx.finditer(text):
            g = m.groupdict()
            if not (1 <= int(g["day"]) <= 31) or not _plausible_year(g.get("year"), today):
                continue
            # Without a year, only clear dates count ("Wed 6 Aug", "6th Aug"), not "2 May" in a sentence.
            if not g.get("year") and not (g.get("wd") or g.get("ord")):
                continue
            try:
                _month_num(g["mon"])
            except ValueError:
                continue
            if free(m.start(), m.end()):
                found.append(Found(m.start(), m.end(), m.group(0), writer(m)))
    for m in _NUMERIC.finditer(text):
        d, mo = int(m.group("day")), int(m.group("mon"))
        if 1 <= d <= 31 and 1 <= mo <= 12 and _plausible_year(m.group("year"), today) and free(m.start(), m.end()):
            found.append(Found(m.start(), m.end(), m.group(0), _write_numeric(m)))
    for m in _ISO.finditer(text):
        if 1 <= int(m.group("mon")) <= 12 and _plausible_year(m.group("year"), today) and free(m.start(), m.end()):
            found.append(Found(m.start(), m.end(), m.group(0), lambda d: d.isoformat()))
    return sorted(found, key=lambda f: f.start)


def rewrite(text: str, lesson: dt.date, today: dt.date | None = None) -> str:
    """`text` with every lesson-style date changed to `lesson`, in the same format."""
    out, last = [], 0
    for f in find_dates(text, today):
        out += [text[last:f.start], f.write(lesson)]
        last = f.end
    return "".join(out) + text[last:]


def next_school_day(today: dt.date | None = None) -> dt.date:
    """Tomorrow, or Monday after a Friday/weekend."""
    d = (today or dt.date.today()) + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d
