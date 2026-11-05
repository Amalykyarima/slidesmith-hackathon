"""Builds a new .pptx in the teacher's style.

Approach: open the teacher's sample deck, *clone* the most suitable sample slide
for each requested page, replace its text/picture, then delete the original
samples. Fonts, colours, backgrounds, shapes and positions are inherited because
they are literally the teacher's own slides.
"""
from __future__ import annotations

import copy
import datetime as dt
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.oxml.ns import qn
from pptx.util import Emu

from . import dates
from .pptx_analysis import (
    EMU_PER_PT,
    SlideInfo,
    analyze_presentation,
    resolve_pt,
    shape_by_id,
)
from .roles import LESSON_LABEL, ROLES, role_of, slot_key
from .schemas import SlideContent

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SHAPE_TAGS = {qn("p:sp"), qn("p:pic"), qn("p:grpSp"), qn("p:graphicFrame"), qn("p:cxnSp")}
SECTION_EXT_URI = "{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"

LEADING_NUMBER = re.compile(r"^\s*\d{1,2}[.)]\s+")

# Some teachers type their bullets as characters ("• Point"). Keep that habit.
LITERAL_BULLET = re.compile(r"^\s*([\u2022\u25aa\u25e6\u25cf\u2023\-\u2013\u2014*]\s+)")

MIN_TITLE_PT = 24
MIN_BODY_PT = 14

# Which sample slides to try, in order, for each kind of slide we need.
FALLBACKS = {
    "title": ["title", "section", "content", "image"],
    "section": ["section", "title", "content", "image"],
    "content": ["content", "image", "title", "section"],
    "image": ["image", "content", "title", "section"],
}


@dataclass
class Target:
    slide: object
    title: object | None = None
    body: object | None = None
    picture_els: list = field(default_factory=list)
    info: SlideInfo | None = None


# --------------------------------------------------------------------------- #
# Cloning
# --------------------------------------------------------------------------- #
def _remap_rids(element, rid_map: dict[str, str]) -> None:
    prefix = f"{{{R_NS}}}"
    for node in element.iter():
        for key, value in list(node.attrib.items()):
            if key.startswith(prefix) and value in rid_map:
                node.set(key, rid_map[value])


def clone_slide(prs, src):
    new = prs.slides.add_slide(src.slide_layout)
    sp_tree = new.shapes._spTree
    for el in list(sp_tree):
        if el.tag in SHAPE_TAGS:
            sp_tree.remove(el)

    rid_map: dict[str, str] = {}
    for r_id, rel in src.part.rels.items():
        if rel.reltype.endswith("/slideLayout") or rel.reltype.endswith("/notesSlide"):
            continue
        if rel.is_external:
            rid_map[r_id] = new.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
        else:
            rid_map[r_id] = new.part.relate_to(rel.target_part, rel.reltype)

    for el in src.shapes._spTree:
        if el.tag in SHAPE_TAGS:
            clone = copy.deepcopy(el)
            _remap_rids(clone, rid_map)
            sp_tree.append(clone)

    src_bg = src._element.cSld.find(qn("p:bg"))
    if src_bg is not None:
        bg = copy.deepcopy(src_bg)
        _remap_rids(bg, rid_map)
        c_sld = new._element.cSld
        existing = c_sld.find(qn("p:bg"))
        if existing is not None:
            c_sld.remove(existing)
        c_sld.insert(0, bg)
    return new


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def _para_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("a:t")))


def refresh_dates(slide, lesson: dt.date) -> int:
    """Dates copied from the sample ("24th Sep 2026") become the lesson's date, written
    the same way. Runs keep their formatting; a date split over runs ends up in the first.
    Auto-updating date fields are left to PowerPoint. Returns how many were changed."""
    changed = 0
    for p in slide.shapes._spTree.iter(qn("a:p")):
        ts = [t for t in p.iter(qn("a:t")) if t.getparent().tag == qn("a:r")]
        text = "".join(t.text or "" for t in ts)
        found = dates.find_dates(text)
        if not found:
            continue
        spans, pos = [], 0
        for t in ts:
            spans.append((t, pos, pos + len(t.text or "")))
            pos += len(t.text or "")
        for f in reversed(found):  # back to front keeps earlier offsets valid
            new, placed = f.write(lesson), False
            for t, a, b in spans:
                if b <= f.start or a >= f.end:
                    continue
                cut_a, cut_b = max(f.start, a) - a, min(f.end, b) - a
                old = t.text or ""
                t.text = old[:cut_a] + ("" if placed else new) + old[cut_b:]
                placed = True
            changed += 1
    return changed


def _set_para_text(p, text: str) -> None:
    for extra in [*p.findall(qn("a:br")), *p.findall(qn("a:fld"))]:
        p.remove(extra)
    runs = p.findall(qn("a:r"))
    if runs:
        first = runs[0]
        for r in runs[1:]:
            p.remove(r)
    else:
        first = etree.Element(qn("a:r"))
        end = p.find(qn("a:endParaRPr"))
        if end is not None:
            rpr = copy.deepcopy(end)
            rpr.tag = qn("a:rPr")
            first.append(rpr)
            end.addprevious(first)
        else:
            p.append(first)
        etree.SubElement(first, qn("a:t"))
    rpr = first.find(qn("a:rPr"))
    if rpr is not None:
        # Links in the sample point at the old lesson's resources.
        for link in rpr.findall(qn("a:hlinkClick")):
            rpr.remove(link)
    t = first.find(qn("a:t"))
    if t is None:
        t = etree.SubElement(first, qn("a:t"))
    t.text = text


_AFTER_BULLET = (qn("a:tabLst"), qn("a:defRPr"), qn("a:extLst"))


def _set_no_bullet(p) -> None:
    """Explicit <a:buNone/>, placed where the schema expects it (before tabLst/defRPr)."""
    ppr = p.find(qn("a:pPr"))
    if ppr is None:
        ppr = etree.Element(qn("a:pPr"))
        p.insert(0, ppr)
    for tag in ("a:buNone", "a:buAutoNum", "a:buChar", "a:buBlip"):
        for el in ppr.findall(qn(tag)):
            ppr.remove(el)
    none = etree.Element(qn("a:buNone"))
    anchor = next((c for c in ppr if c.tag in _AFTER_BULLET), None)
    if anchor is not None:
        anchor.addprevious(none)
    else:
        ppr.append(none)


def _ensure_spacing(p) -> None:
    ppr = p.find(qn("a:pPr"))
    if ppr is None:
        ppr = etree.Element(qn("a:pPr"))
        p.insert(0, ppr)
    if ppr.find(qn("a:spcBef")) is not None or ppr.find(qn("a:spcAft")) is not None:
        return
    spc = etree.Element(qn("a:spcBef"))
    etree.SubElement(spc, qn("a:spcPts")).set("val", "600")
    ln = ppr.find(qn("a:lnSpc"))
    if ln is not None:
        ln.addnext(spc)
    else:
        ppr.insert(0, spc)


def _estimate_height(lines: list[str], pt: float, width_pt: float) -> float:
    # Average glyph ~0.47em in common teaching fonts (Calibri, Gill Sans, Arial is ~0.5).
    # Wrap word by word rather than by raw character count, so lines aren't overestimated.
    chars_per_line = max(width_pt / (pt * 0.47), 1)
    n_lines = sum(_wrapped_lines(line, chars_per_line) for line in lines)
    return n_lines * pt * 1.15 + max(len(lines) - 1, 0) * pt * 0.25


def _wrapped_lines(text: str, chars_per_line: float) -> int:
    count, current = 1, 0
    for word in text.split() or [""]:
        need = len(word) if current == 0 else current + 1 + len(word)
        if need <= chars_per_line or current == 0:
            current = need
        else:
            count, current = count + 1, len(word)
        while current > chars_per_line:  # a single word longer than the line
            count, current = count + 1, current - int(chars_per_line)
    return count


def _fit_pt(shape, lines: list[str], base_pt: float, min_pt: float, indent_pt: float = 0) -> tuple[float, bool]:
    width = (shape.width or 0) / EMU_PER_PT - 14.4 - indent_pt
    height = (shape.height or 0) / EMU_PER_PT - 7.2
    if width <= 0 or height <= 0:
        return base_pt, True
    pt = base_pt
    while True:
        if _estimate_height(lines, pt, width) <= height:
            return pt, True
        if pt - 1 < min_pt:
            return max(pt, min_pt), False
        pt -= 1


def _apply_size(txbody, pt: float) -> None:
    for p in txbody.findall(qn("a:p")):
        for r in p.findall(qn("a:r")):
            rpr = r.find(qn("a:rPr"))
            if rpr is None:
                rpr = etree.Element(qn("a:rPr"))
                r.insert(0, rpr)
            rpr.set("sz", str(int(pt * 100)))
        end = p.find(qn("a:endParaRPr"))
        if end is not None:
            end.set("sz", str(int(pt * 100)))


# "Alcohol   5th Nov 2026" / "Alcohol | 5th Nov 2026" / "Alcohol 5th Nov 2026"
_TITLE_PARTS = re.compile(r"\s{2,}|\s+\|\s+")
_DATE_TAIL = re.compile(r"^(.*?\S)\s+(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?\s+\d{4})$")
_GAP = re.compile(r"\s{4,}")


def _split_title(text: str) -> tuple[str, str] | None:
    parts = [p for p in _TITLE_PARTS.split(text.strip()) if p]
    if len(parts) == 2:
        return parts[0], parts[1]
    m = _DATE_TAIL.match(text.strip())
    return (m.group(1), m.group(2)) if m else None


def _fill_gap_title(p, left: str, right: str) -> bool:
    """Headings laid out as "Topic <spaces> Date" keep that layout: same overall
    length, so the date stays pushed to the right, and each part keeps its own
    run formatting (e.g. underlined words but not underlined spaces)."""
    runs = p.findall(qn("a:r"))
    texts = [(r.find(qn("a:t")).text or "") if r.find(qn("a:t")) is not None else "" for r in runs]
    full = "".join(texts)
    m = re.match(r"^\s*(\S.*?)(\s{4,})(\S.*?)\s*$", full)
    if not m:
        return False
    gap = " " * max(4, len(m.group(1)) + len(m.group(2)) + len(m.group(3)) - len(left) - len(right))
    for extra in [*p.findall(qn("a:br")), *p.findall(qn("a:fld"))]:
        p.remove(extra)
    left_i = next((i for i, t in enumerate(texts) if t.strip()), None)
    gap_i = next((i for i, t in enumerate(texts) if i > (left_i or 0) and t and not t.strip()), None)
    right_i = next((i for i, t in enumerate(texts) if gap_i is not None and i > gap_i and t.strip()), None)
    if left_i is not None and gap_i is not None and right_i is not None:
        keep = {left_i: left, gap_i: gap, right_i: right}
        for i, r in enumerate(runs):
            if i in keep:
                r.find(qn("a:t")).text = keep[i]
            else:
                p.remove(r)
    else:
        _set_para_text(p, f"{left}{gap}{right}")
    for r in p.findall(qn("a:r")):
        rpr = r.find(qn("a:rPr"))
        for link in (rpr.findall(qn("a:hlinkClick")) if rpr is not None else []):
            rpr.remove(link)
    return True


def _stop_above_bars(shape, slide) -> None:
    """Some teachers' text boxes run behind a footer bar; text placed there is hidden.
    End the box where a full-width strip covering its lower part begins."""
    try:
        slide_w = slide.part.package.presentation_part.presentation.slide_width
        top, height = shape.top, shape.height
    except (AttributeError, TypeError):
        return
    if top is None or height is None:
        return
    for other in slide.shapes:
        if other.shape_id == shape.shape_id or None in (other.top, other.width, other.height):
            continue
        if other.width >= 0.85 * slide_w and top + height / 2 < other.top < top + height:
            shape.height = other.top - top - Emu(45720)


def _stop_before_badges(shape, slide) -> None:
    """Her short heading ended before a small badge or icon on the same line ("You do"
    climate badge, logo). A longer new heading would run underneath it: end the box
    just before the first such picture to its right."""
    try:
        slide_w = slide.part.package.presentation_part.presentation.slide_width
        left, top, width, height = shape.left, shape.top, shape.width, shape.height
    except (AttributeError, TypeError):
        return
    if None in (left, top, width, height):
        return
    middle = top + height / 2
    for other in slide.shapes:
        if other.shape_id == shape.shape_id or None in (other.left, other.top, other.width, other.height):
            continue
        if getattr(other, "has_text_frame", False) and other.text_frame.text.strip():
            continue  # text boxes are handled elsewhere; only pictures, icons and groups here
        small = other.width < 0.2 * slide_w
        on_line = other.top < middle < other.top + other.height or top <= other.top + other.height / 2 <= top + height
        inside = left + 0.4 * width < other.left < left + width
        if small and on_line and inside:
            width = min(width, other.left - left - Emu(45720))
    if width < shape.width:
        shape.width = width


def _grow_into_free_space(shape, slide) -> None:
    """Long text first uses empty space below its box (down to the next shape or the
    slide's bottom margin) before the font is shrunk."""
    try:
        slide_h = slide.part.package.presentation_part.presentation.slide_height
        left, top, width, height = shape.left, shape.top, shape.width, shape.height
    except (AttributeError, TypeError):
        return
    if None in (left, top, width, height):
        return
    bottom = top + height
    limit = int(slide_h * 0.94)
    for other in slide.shapes:
        if other.shape_id == shape.shape_id or None in (other.left, other.top, other.width, other.height):
            continue
        overlaps_x = other.left < left + width and other.left + other.width > left
        if overlaps_x and other.top >= bottom:
            limit = min(limit, other.top - Emu(45720))  # leave ~0.05" before the next shape
    if limit > bottom:
        shape.height = limit - top


def fill_text(shape, slide, lines: list[str], is_title: bool, warnings: list[str], label: str) -> None:
    lines = [ln.strip() for ln in lines if ln and ln.strip()]
    if not lines:
        lines = [""]
    tx = shape.text_frame._txBody
    paras = tx.findall(qn("a:p"))
    template = max(paras, key=lambda p: len(_para_text(p)), default=None)
    template = copy.deepcopy(template) if template is not None else etree.Element(qn("a:p"))
    base_pt = resolve_pt(shape, slide, is_title)
    match = None if is_title else LITERAL_BULLET.match(_para_text(template))
    prefix = match.group(1) if match else ""
    ppr = template.find(qn("a:pPr"))
    auto_numbered = ppr is not None and ppr.find(qn("a:buAutoNum")) is not None
    if is_title:
        # A heading never keeps list numbering from the sample or its layout ("1. Turn and Talk").
        _set_no_bullet(template)
    if auto_numbered and not is_title:
        # PowerPoint already numbers these lines; typed numbers would show twice ("1. 1.").
        lines = [LEADING_NUMBER.sub("", ln) for ln in lines]

    # A label line that the sample also starts with ("Retrieval Practice:") keeps the
    # sample's own formatting for it, e.g. unnumbered above a numbered list.
    first = paras[0] if paras else None
    label_template = None
    if not is_title and first is not None and lines and _para_text(first).strip().lower() == lines[0].lower():
        label_template = copy.deepcopy(first)

    for p in paras:
        tx.remove(p)
    for i, line in enumerate(lines):
        p = copy.deepcopy(label_template if i == 0 and label_template is not None else template)
        parts = _split_title(line) if is_title and len(lines) == 1 else None
        if is_title and len(lines) == 1 and parts is None:
            # Her heading is "Topic <spaces> Date": keep the (refreshed) date beside the new topic.
            gap = re.match(r"^\s*(\S.*?)(\s{4,})(\S.*?)\s*$", _para_text(p))
            if gap and (d := dates.find_dates(gap.group(3))) and d[0].text.strip() == gap.group(3).strip():
                parts = (line, gap.group(3).strip())
        if parts and _GAP.search(_para_text(p)) and _fill_gap_title(p, *parts):
            pass
        else:
            _set_para_text(p, prefix + line if line and not LITERAL_BULLET.match(line) else line)
        if len(lines) > 1 and not shape.is_placeholder:
            _ensure_spacing(p)
        tx.append(p)

    indent = 0 if is_title else 18
    if is_title:
        _stop_before_badges(shape, slide)
    if not is_title:
        _stop_above_bars(shape, slide)
        if not _fit_pt(shape, lines, base_pt, base_pt, indent)[1]:
            _grow_into_free_space(shape, slide)
    pt, fits = _fit_pt(shape, lines, base_pt, MIN_TITLE_PT if is_title else MIN_BODY_PT, indent)
    if pt < base_pt:
        _apply_size(tx, pt)
    if not fits:
        warnings.append(f"{label}: text is long for this style and may overflow. Consider shortening it.")


# --------------------------------------------------------------------------- #
# Pictures
# --------------------------------------------------------------------------- #
def _place_picture(slide, box: tuple[int, int, int, int], image_path: Path, alt: str, replace_el=None):
    left, top, width, height = box
    with Image.open(image_path) as im:
        iw, ih = im.size
    scale = min(width / iw, height / ih)
    pw, ph = int(iw * scale), int(ih * scale)
    pic = slide.shapes.add_picture(
        str(image_path),
        Emu(int(left + (width - pw) / 2)),
        Emu(int(top + (height - ph) / 2)),
        Emu(pw),
        Emu(ph),
    )
    pic._element.nvPicPr.cNvPr.set("descr", alt[:250])
    if replace_el is not None:
        tree = slide.shapes._spTree
        tree.remove(pic._element)
        idx = list(tree).index(replace_el)
        tree.remove(replace_el)
        tree.insert(idx, pic._element)
    return pic


def _box_of(shape) -> tuple[int, int, int, int]:
    return int(shape.left), int(shape.top), int(shape.width), int(shape.height)


def _element_box(el) -> tuple[int, int, int, int] | None:
    xfrm = el.find(f".//{qn('a:xfrm')}")
    if xfrm is None:
        return None
    off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
    if off is None or ext is None:
        return None
    return int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))


def _side_image(prs, target: Target, image_path: Path, alt: str) -> None:
    """Exemplar has no picture: narrow the body and put the image beside it."""
    slide_w, slide_h = prs.slide_width, prs.slide_height
    margin = int(0.5 * 914400)
    gap = int(0.3 * 914400)
    body = target.body
    if body is not None:
        left, top, width, height = _box_of(body)
        new_w = int(width * 0.54)
        body.left, body.top, body.width, body.height = Emu(left), Emu(top), Emu(new_w), Emu(height)
        img_left = left + new_w + gap
        box = (img_left, top, max(slide_w - img_left - margin, int(slide_w * 0.2)), height)
    else:
        top = int(slide_h * 0.32)
        box = (int(slide_w * 0.5), top, int(slide_w * 0.5) - margin, int(slide_h * 0.6))
    _place_picture(target.slide, box, image_path, alt)


# --------------------------------------------------------------------------- #
# Choosing a sample slide
# --------------------------------------------------------------------------- #
def page_role(content: SlideContent) -> str | None:
    """Which routine slide a page is: the AI says so, or its heading / first line does."""
    if content.role in ROLES:
        return content.role
    return role_of(content.title) or (role_of(content.bullets[0]) if content.bullets else None)


def rank_exemplars(
    infos: list[SlideInfo],
    kind: str,
    usage: Counter,
    role: str | None = None,
    needs_body: bool = False,
) -> list[tuple[SlideInfo, bool]]:
    """Sample slides for a page, best first, as (sample, matched_by_role).

    A page with a routine role ("Turn and Talk", "Retrieval Practice"...) uses a sample
    with the same role. Ordinary teaching pages use ordinary or "I do" samples, never
    another routine's slide. A page with bullet points prefers samples that have a body
    to hold them; samples without one only come last. Cleaner samples (less sample
    content to strip) win, then the least-used one so repeated pages vary.
    """
    order = FALLBACKS[kind]
    usable = [i for i in infos if not i.complex and i.title_id is not None] or [
        i for i in infos if not i.complex
    ] or infos

    def holds_text(i: SlideInfo) -> int:
        return 0 if (not needs_body or i.body_id is not None) else 1

    def role_rank(i: SlideInfo):
        kind_rank = order.index(i.kind) if i.kind in order else len(order)
        return (holds_text(i), i.clutter, kind_rank, usage[i.index], i.index)

    ranked: list[tuple[SlideInfo, bool]] = []
    seen: set[int] = set()

    def add(pool, by_role: bool, key) -> None:
        for i in sorted(pool, key=key):
            if i.index not in seen:
                seen.add(i.index)
                ranked.append((i, by_role))

    if role:
        add([i for i in usable if i.role == role], True, role_rank)

    for allowed in ({None, "i_do"}, set(ROLES) - {"exit"} | {None}):
        candidates = [i for i in usable if i.role in allowed]
        for wanted in order:
            add([i for i in candidates if i.kind == wanted], False,
                lambda i: (holds_text(i), i.clutter, usage[i.index], i.index))
    # Samples that can't hold the text go after every sample that can.
    ranked.sort(key=lambda pair: holds_text(pair[0]))  # stable: keeps the order above
    return ranked or [(infos[0], False)]


def pick_exemplar(
    infos: list[SlideInfo], kind: str, usage: Counter, role: str | None = None, needs_body: bool = False
) -> tuple[SlideInfo, bool]:
    """Best single sample for a page (see `rank_exemplars`)."""
    return rank_exemplars(infos, kind, usage, role, needs_body)[0]


def _layout_target(prs, kind: str) -> Target:
    """Fallback for style decks that only contain layouts and no sample slides."""
    title_types = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}
    body_types = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.SUBTITLE}

    def score(layout) -> int:
        types = {ph.placeholder_format.type for ph in layout.placeholders}
        name = layout.name.lower()
        s = 0
        if types & title_types:
            s += 2
        if types & body_types:
            s += 2
        if kind == "title":
            s += 4 if PP_PLACEHOLDER.CENTER_TITLE in types else 0
            s += 2 if "title" in name and "only" not in name else 0
        elif kind == "section":
            s += 4 if "section" in name else 0
        else:
            s += 3 if PP_PLACEHOLDER.OBJECT in types or PP_PLACEHOLDER.BODY in types else 0
            s -= 4 if PP_PLACEHOLDER.CENTER_TITLE in types else 0
            s += 2 if "content" in name or "bullet" in name else 0
        return s

    layout = max(prs.slide_layouts, key=score)
    slide = prs.slides.add_slide(layout)
    title = body = None
    for ph in slide.placeholders:
        t = ph.placeholder_format.type
        if t in title_types and title is None:
            title = ph
        elif t in body_types and body is None:
            body = ph
    return Target(slide=slide, title=title, body=body)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
MAX_ATTEMPTS = 4  # sample slides tried per page before settling for the best attempt


def _missing_warning(label: str, missing: list[str]) -> str:
    shown = "; ".join(f'"{m[:50]}{"…" if len(m) > 50 else ""}"' for m in missing[:3])
    more = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
    return (f"{label}: {len(missing)} line(s) didn't fit on any of your sample slides and are missing: "
            f"{shown}{more}. Split this page in two or add a sample slide with more room.")


def _norm_text(text: str) -> str:
    return " ".join(text.split()).lower()


def _expected_lines(content: SlideContent) -> list[str]:
    """Every piece of text the page must show: title, bullets (or subtitle)."""
    lines = [content.title] if content.title.strip() else []
    if content.bullets:
        lines += content.bullets
    elif content.subtitle.strip():
        lines.append(content.subtitle)
    return [ln for ln in lines if ln.strip()]


def missing_text(slide, content: SlideContent) -> list[str]:
    """Lines of the page that didn't make it onto the slide (numbering/bullet marks ignored)."""
    shown = _norm_text(" ".join(sh.text_frame.text for sh in slide.shapes if sh.has_text_frame))
    missing = []
    for line in _expected_lines(content):
        core = LEADING_NUMBER.sub("", LITERAL_BULLET.sub("", line.strip()))
        if _norm_text(core) not in shown:
            missing.append(line)
    return missing


def _delete_slide(prs, slide) -> None:
    sld_id_lst = prs.slides._sldIdLst
    for sld_id in list(sld_id_lst):
        if prs.part.related_part(sld_id.rId) is slide.part:
            prs.part.drop_rel(sld_id.rId)
            sld_id_lst.remove(sld_id)
            return


def _label_kind(text: str) -> str | None:
    """"lo" for an "LO: ..." / "Learning objective: ..." line, "keywords" for "Keywords: ...". """
    m = LESSON_LABEL.match(text or "")
    if not m:
        return None
    return "keywords" if m.group(1).lower().startswith("key") else "lo"


def _value_box(slide, label_shape):
    """A bare "LO:" box whose words sit in a separate box just to its right."""
    try:
        right, top, bottom = label_shape.left + label_shape.width, label_shape.top, label_shape.top + label_shape.height
    except TypeError:
        return None
    for other in slide.shapes:
        if other.shape_id == label_shape.shape_id or not other.has_text_frame or not other.text_frame.text.strip():
            continue
        if None in (other.left, other.top, other.height):
            continue
        if right - Emu(91440) <= other.left <= right + Emu(914400) and other.top < bottom and other.top + other.height > top:
            return other
    return None


def _fill_label(shape, value: str) -> None:
    """Keep her "LO:" / "Keywords:" label and its formatting; replace what follows it."""
    paras = shape.text_frame._txBody.findall(qn("a:p"))
    first = next((p for p in paras if ":" in _para_text(p) or "-" in _para_text(p)), paras[0])
    runs = first.findall(qn("a:r"))
    text, cut = "", None
    for k, r in enumerate(runs):
        t = r.find(qn("a:t"))
        before = len(text)
        text += t.text or ""
        m = re.search(r"[:\-]", text)
        if m and cut is None:
            cut = k
            keep = m.end() - before
            t.text = (t.text or "")[:keep]
    if cut is None or not runs:
        _set_para_text(first, value)
    else:
        after = runs[cut + 1] if cut + 1 < len(runs) else None
        if after is None:  # label and words were one run: copy it for the words, without bold
            after = copy.deepcopy(runs[cut])
            rpr = after.find(qn("a:rPr"))
            if rpr is not None and rpr.get("b") == "1":
                rpr.set("b", "0")
            runs[cut].addnext(after)
        after.find(qn("a:t")).text = " " + value
        for extra in runs[cut + 2:]:
            first.remove(extra)
    for p in paras:  # one line only
        if p is not first:
            shape.text_frame._txBody.remove(p)


def _apply_lesson_labels(slide, shape, labels: dict[str, str]) -> bool:
    """Her LO / Keywords strip gets the new lesson's words. False = nothing to put there."""
    kind = _label_kind(_text_of(shape))
    value = (labels or {}).get(kind or "", "").strip()
    if not value:
        return False
    after_label = re.sub(r"^\s*[^:\-]*[:\-]\s*", "", _text_of(shape)).strip()
    partner = _value_box(slide, shape) if not after_label else None
    if partner is not None:
        _set_para_text(partner.text_frame._txBody.findall(qn("a:p"))[0], value)
        for p in partner.text_frame._txBody.findall(qn("a:p"))[1:]:
            partner.text_frame._txBody.remove(p)
    else:
        _fill_label(shape, value)
    return True


def _text_of(shape) -> str:
    return shape.text_frame.text if getattr(shape, "has_text_frame", False) else ""


def _render_page(prs, originals, info: SlideInfo | None, kind: str, content: SlideContent,
                 image: Path | None, label: str, warnings: list[str], lesson: dt.date | None = None,
                 labels: dict[str, str] | None = None):
    """Clone the sample (or a layout), place the picture, then fill the text."""
    bullets = list(content.bullets)
    slot_lines: dict[int, str] = {}
    if info is not None:
        slide = clone_slide(prs, originals[info.index])
        if lesson:
            refresh_dates(slide, lesson)  # before the new text goes in: only the sample's dates change
        target = Target(
            slide=slide,
            title=shape_by_id(slide, info.title_id) if info.title_id is not None else None,
            body=shape_by_id(slide, info.body_id) if info.body_id is not None else None,
            picture_els=[
                shape_by_id(slide, pid)._element
                for pid in info.picture_ids
                if shape_by_id(slide, pid) is not None
            ],
            info=info,
        )
        # Lines whose label matches a labelled box on the sample ("impair (verb): …" ->
        # the definition banner, "Application task: …" -> its box) go into that box.
        for sid, key in info.slots.items():
            idx = next((k for k, b in enumerate(bullets) if slot_key(b) == key), None)
            if idx is not None and shape_by_id(slide, sid) is not None:
                slot_lines[sid] = bullets.pop(idx)
        for sid in info.stale_ids:
            if sid in slot_lines:
                continue
            stale = shape_by_id(slide, sid)
            if stale is None:
                continue
            if _label_kind(_text_of(stale)):
                if _apply_lesson_labels(slide, stale, labels or {}):
                    continue  # her LO / Keywords strip, now about this lesson
                partner = _value_box(slide, stale)  # the old lesson's words beside a bare "LO:"
                if partner is not None and partner.shape_id not in (info.title_id, info.body_id):
                    partner._element.getparent().remove(partner._element)
            stale._element.getparent().remove(stale._element)
    else:
        target = _layout_target(prs, kind)
        slide = target.slide

    body_lines = bullets
    if content.kind in ("title", "section") and not body_lines:
        body_lines = [content.subtitle] if content.subtitle else []

    # ---- picture first: it decides how much room the text has ----------- #
    alt = f"Image for {label}: {content.title}"
    if image:
        biggest = max(
            target.picture_els,
            key=lambda e: (_element_box(e) or (0, 0, 0, 0))[2] * (_element_box(e) or (0, 0, 0, 0))[3],
            default=None,
        )
        box = _element_box(biggest) if biggest is not None else None
        if box and (target.body is not None or not body_lines):
            # The sample has a picture spot and somewhere for the text: use her layout.
            _place_picture(slide, box, image, alt, replace_el=biggest)
        else:
            # No picture spot (or nowhere for the text): her text slide, picture beside it.
            for el in target.picture_els:
                if el.getparent() is not None:
                    el.getparent().remove(el)
            _side_image(prs, target, image, alt)
    else:
        for el in target.picture_els:
            if el.getparent() is not None:
                el.getparent().remove(el)

    # ---- text ------------------------------------------------------------ #
    if target.title is not None:
        fill_text(target.title, slide, [content.title or label], True, warnings, f"{label} title")
    for sid, line in slot_lines.items():
        fill_text(shape_by_id(slide, sid), slide, [line], False, warnings, f"{label} box")
    if target.body is not None:
        if body_lines or not target.body.is_placeholder:
            fill_text(target.body, slide, body_lines or [""], False, warnings, f"{label} body")
        else:
            target.body._element.getparent().remove(target.body._element)
            target.body = None

    # ---- notes ----------------------------------------------------------- #
    if content.notes.strip():
        slide.notes_slide.notes_text_frame.text = content.notes.strip()
    return slide


def build_deck(
    style_path: Path,
    contents: list[SlideContent],
    image_paths: dict[int, Path],
    out_path: Path,
    deck_title: str = "",
    videos: dict[int, str] | None = None,
    lesson_date: dt.date | None = None,
    lesson_labels: dict[str, str] | None = None,
) -> list[str]:
    """`videos`: page -> video link. When that page's picture is the video's thumbnail
    (videos.thumbnail), clicking the picture opens the video; when the teacher also gave
    a picture, a "Watch the video" line links to it instead."""
    from . import videos as vids

    videos = videos or {}
    lesson = lesson_date or dates.next_school_day()
    prs = Presentation(str(style_path))
    warnings: list[str] = []
    originals = list(prs.slides)
    infos = analyze_presentation(prs)
    usage: Counter = Counter()
    noted: set[tuple[str, str]] = set()

    def finish_video(slide, content, image) -> None:
        url = videos.get(content.page)
        if not url:
            return
        if vids.is_thumbnail(image):
            vids.link_picture(slide, image, url)
        else:
            vids.link_text(slide, vids.WATCH_LINE, url)

    for content in contents:
        label = f"Slide {content.page}"
        image = image_paths.get(content.page)
        kind = "image" if image else content.kind
        if url := videos.get(content.page):
            extra = {"notes": f"{content.notes.strip()}\n\nVideo: {url}".strip()}
            if not vids.is_thumbnail(image):
                extra["bullets"] = [*content.bullets, vids.WATCH_LINE]
            content = content.model_copy(update=extra)

        if not infos:
            page_warnings: list[str] = []
            slide = _render_page(prs, originals, None, kind, content, image, label, page_warnings, lesson, lesson_labels)
            finish_video(slide, content, image)
            warnings += page_warnings
            if missing := missing_text(slide, content):
                warnings.append(_missing_warning(label, missing))
            continue

        # Try the best samples in turn until one shows every line of the page.
        chosen = next((i for i in infos if content.sample and i.index == content.sample - 1 and not i.complex), None)
        role = page_role(content) or (chosen.role if chosen else None)
        candidates = rank_exemplars(infos, kind, usage, role, needs_body=bool(content.bullets))
        if chosen is not None:  # the teacher (or the AI) named her slide: try it first
            candidates = [(chosen, True)] + [c for c in candidates if c[0] is not chosen]
        attempts = []  # (missing, slide, info, by_role, page_warnings)
        for info, by_role in candidates[:MAX_ATTEMPTS]:
            page_warnings = []
            slide = _render_page(prs, originals, info, kind, content, image, label, page_warnings, lesson, lesson_labels)
            missing = missing_text(slide, content)
            attempts.append((missing, slide, info, by_role, page_warnings))
            if not missing:
                break
        best = min(attempts, key=lambda a: len(a[0]))
        for attempt in attempts:
            if attempt is not best:
                _delete_slide(prs, attempt[1])
        missing, slide, info, by_role, page_warnings = best
        finish_video(slide, content, image)
        usage[info.index] += 1
        warnings += page_warnings
        if missing:
            warnings.append(_missing_warning(label, missing))
        if not by_role and kind != "image" and info.kind != kind and (kind, info.kind) not in noted:
            noted.add((kind, info.kind))
            warnings.append(
                f"Your style has no '{kind}' sample slide, so '{info.kind}' samples were used instead. "
                f"Add a sample slide like that for better results."
            )

    # Web addresses typed on the new slides become clickable.
    for slide in list(prs.slides)[len(originals):]:
        vids.link_urls(slide)

    # Drop the original sample slides, keep only the new ones.
    sld_id_lst = prs.slides._sldIdLst
    for sld_id in list(sld_id_lst)[: len(originals)]:
        prs.part.drop_rel(sld_id.rId)
        sld_id_lst.remove(sld_id)

    # Sections reference slide ids that no longer exist; PowerPoint would "repair" the file.
    ext_lst = prs._element.find(qn("p:extLst"))
    if ext_lst is not None:
        for ext in list(ext_lst):
            if ext.get("uri") == SECTION_EXT_URI:
                ext_lst.remove(ext)

    if deck_title:
        prs.core_properties.title = deck_title
    prs.save(str(out_path))
    return warnings
