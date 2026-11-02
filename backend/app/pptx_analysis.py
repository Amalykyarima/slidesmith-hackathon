"""Reads an uploaded .pptx and works out its "style".

Teachers build slides in very different ways: some use proper layouts with
placeholders, many just drop text boxes on a blank slide. So instead of relying
on layouts, we treat every sample slide as an *exemplar* and figure out which
shape is the title, which is the body, and where the pictures are.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.slide import Slide

from .roles import is_lesson_label, role_of

EMU_PER_PT = 12700

_SKIP_PLACEHOLDERS = {
    PP_PLACEHOLDER.DATE,
    PP_PLACEHOLDER.FOOTER,
    PP_PLACEHOLDER.SLIDE_NUMBER,
}
_TITLE_PLACEHOLDERS = {
    PP_PLACEHOLDER.TITLE,
    PP_PLACEHOLDER.CENTER_TITLE,
    PP_PLACEHOLDER.VERTICAL_TITLE,
}
_SUBTITLE_PLACEHOLDERS = {PP_PLACEHOLDER.SUBTITLE}


@dataclass
class SlideInfo:
    index: int
    kind: str  # title | content | image | section
    title_id: int | None = None
    body_id: int | None = None
    picture_ids: list[int] = field(default_factory=list)  # large pictures only
    stale_ids: list[int] = field(default_factory=list)  # extra text boxes holding sample content
    complex: bool = False  # contains tables / charts we can't safely refill
    title_pt: float = 36
    body_pt: float = 20
    preview_text: str = ""
    role: str | None = None  # routine role, e.g. "retrieval", "turn_and_talk" (see roles.py)
    clutter: int = 0  # extra sample content that has to be stripped; lower is a cleaner exemplar

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "has_title": self.title_id is not None,
            "has_body": self.body_id is not None,
            "pictures": len(self.picture_ids),
            "complex": self.complex,
            "preview_text": self.preview_text,
            "role": self.role,
        }


# --------------------------------------------------------------------------- #
# Shape helpers
# --------------------------------------------------------------------------- #
def shape_by_id(slide: Slide, shape_id: int):
    for shp in slide.shapes:
        if shp.shape_id == shape_id:
            return shp
    return None


def _ph_type(shape):
    if not shape.is_placeholder:
        return None
    try:
        return shape.placeholder_format.type
    except Exception:  # noqa: BLE001
        return None


def _area(shape) -> int:
    try:
        return int((shape.width or 0) * (shape.height or 0))
    except Exception:  # noqa: BLE001
        return 0


def _is_picture(shape) -> bool:
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        return True
    # Picture placeholders that have been filled
    return shape._element.tag == qn("p:pic")


def _is_decoration(pic, slide_area: int, repeated: frozenset[str]) -> bool:
    """Part of the style, not the lesson: full-bleed backgrounds, and small images
    repeated across slides (logos, icons, badges). A big photo reused on two slides
    is still lesson content."""
    area = _area(pic)
    if area >= 0.85 * slide_area:
        return True
    return area < 0.05 * slide_area and _image_hash(pic) in repeated


def _overlap_ratio(shape, other) -> float:
    """Share of `shape`'s area that `other` covers."""
    try:
        x1, y1 = max(shape.left, other.left), max(shape.top, other.top)
        x2 = min(shape.left + shape.width, other.left + other.width)
        y2 = min(shape.top + shape.height, other.top + other.height)
    except TypeError:
        return 0.0
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1) / max(_area(shape), 1)


def _text(shape) -> str:
    return shape.text_frame.text.strip() if shape.has_text_frame else ""


def _is_title_like(shape) -> bool:
    """Short text in one or two lines: a heading, not a box of questions."""
    text = _text(shape)
    paras = [p for p in shape.text_frame.paragraphs if p.text.strip()]
    return bool(text) and len(paras) <= 2 and len(text) <= 100 and not is_lesson_label(text)


def _is_text_candidate(shape) -> bool:
    if not shape.has_text_frame:
        return False
    ph = _ph_type(shape)
    if ph in _SKIP_PLACEHOLDERS:
        return False
    if shape.is_placeholder:
        return True
    return bool(shape.text_frame.text.strip())


def _image_hash(shape) -> str | None:
    try:
        return shape.image.sha1
    except Exception:  # noqa: BLE001
        return None


def _explicit_pt(shape) -> float | None:
    sizes: list[float] = []
    for p in shape.text_frame.paragraphs:
        for r in p.runs:
            if r.font.size:
                sizes.append(r.font.size.pt)
        if p.font.size:
            sizes.append(p.font.size.pt)
    return max(sizes) if sizes else None


def _sz_from(node) -> float | None:
    if node is None:
        return None
    defrpr = node.find(f".//{qn('a:lvl1pPr')}/{qn('a:defRPr')}")
    if defrpr is not None and defrpr.get("sz"):
        return int(defrpr.get("sz")) / 100
    return None


def resolve_pt(shape, slide: Slide, is_title: bool) -> float:
    """Best-effort effective font size for a text shape (explicit > layout > master > default)."""
    explicit = _explicit_pt(shape)
    if explicit:
        return explicit
    if shape.is_placeholder:
        idx = shape.placeholder_format.idx
        layout = slide.slide_layout
        for ph in layout.placeholders:
            if ph.placeholder_format.idx == idx:
                found = _sz_from(ph._element.find(f".//{qn('a:lstStyle')}"))
                if found:
                    return found
        master = layout.slide_master
        for ph in master.placeholders:
            if ph.placeholder_format.type == _ph_type(shape):
                found = _sz_from(ph._element.find(f".//{qn('a:lstStyle')}"))
                if found:
                    return found
        styles = master._element.find(qn("p:txStyles"))
        if styles is not None:
            style = styles.find(qn("p:titleStyle" if is_title else "p:bodyStyle"))
            found = _sz_from(style)
            if found:
                return found
    return 36 if is_title else 20


# --------------------------------------------------------------------------- #
# Slide analysis
# --------------------------------------------------------------------------- #
def analyze_slide(
    slide: Slide, index: int, slide_w: int, slide_h: int, repeated: frozenset[str] = frozenset()
) -> SlideInfo:
    slide_area = slide_w * slide_h
    text_shapes = [s for s in slide.shapes if _is_text_candidate(s)]
    # "Content" pictures are big but not decoration. Full-bleed backgrounds and anything
    # repeated across slides (logos, banners, corner art) are part of the style: keep them.
    big_pictures = [
        s
        for s in slide.shapes
        if _is_picture(s)
        and 0.10 * slide_area < _area(s) < 0.85 * slide_area
        and not _is_decoration(s, slide_area, repeated)
    ]
    # Pictures that can carry a caption: not full-bleed backgrounds, not logos repeated on every slide.
    pictures = [s for s in slide.shapes if _is_picture(s) and not _is_decoration(s, slide_area, repeated)]
    complex_ = any(
        s.shape_type in (MSO_SHAPE_TYPE.TABLE, MSO_SHAPE_TYPE.CHART)
        or getattr(s, "has_table", False)
        or getattr(s, "has_chart", False)
        # content built from grouped cards (picture + caption + text) can't be refilled safely
        or (s.shape_type == MSO_SHAPE_TYPE.GROUP and _area(s) > 0.10 * slide_area)
        for s in slide.shapes
    )

    # --- title ---------------------------------------------------------- #
    title = next((s for s in text_shapes if _ph_type(s) in _TITLE_PLACEHOLDERS), None)
    if title is None and text_shapes:
        # Biggest font wins, ties broken by position (higher first). Prefer heading-like
        # boxes: a long box of questions in a big font is the body, not the title.
        pool = [s for s in text_shapes if _is_title_like(s) and resolve_pt(s, slide, True) >= 12] or text_shapes
        title = sorted(
            pool,
            key=lambda s: (-round(resolve_pt(s, slide, True) / 4), s.top or 0, s.left or 0),
        )[0]

    # --- body ----------------------------------------------------------- #
    rest = [s for s in text_shapes if s is not title]

    def usable_body(s) -> bool:
        # Not a tiny badge ("Climate 1 'I do'"), not a lesson label (LO / Keywords),
        # and not a caption sitting on top of a picture.
        if _area(s) < 0.03 * slide_area or resolve_pt(s, slide, False) < 9:
            return False
        if is_lesson_label(_text(s)):
            return False
        return not any(_overlap_ratio(s, pic) > 0.5 for pic in pictures)

    body = next((s for s in rest if _ph_type(s) in _SUBTITLE_PLACEHOLDERS and usable_body(s)), None)
    body_candidates = [s for s in rest if (_text(s) or s.is_placeholder) and usable_body(s)]
    if body is None and body_candidates:
        placeholders = [s for s in body_candidates if s.is_placeholder]
        # Big box in a readable font: a large box of 14pt links loses to the question in 24pt.
        body = sorted(
            placeholders or body_candidates,
            key=lambda s: -_area(s) * min(resolve_pt(s, slide, False), 40),
        )[0]

    # Text boxes that carry sample content but aren't title/body: big ones are stale
    # sample content, and LO / Keywords labels belong to the sample's lesson. Small
    # footers and badges stay as part of the style.
    # Captions laid over a sample picture go with that picture.
    stale = [
        s.shape_id
        for s in rest
        if s is not body
        and _text(s)
        and (
            _area(s) > 0.08 * slide_area
            or is_lesson_label(_text(s))
            or any(_overlap_ratio(s, pic) > 0.5 for pic in big_pictures)
        )
    ]

    body_text = body.text_frame.text.strip() if body is not None else ""
    body_paragraphs = [p for p in (body.text_frame.paragraphs if body is not None else []) if p.text.strip()]

    if big_pictures and (title is not None or body is not None):
        kind = "image"
    elif body is None:
        kind = "title" if index == 0 else "section"
    elif not body_text:
        # empty body placeholder: on later slides that's the intended bullet area
        kind = "title" if index == 0 else "content"
    elif index == 0 and len(body_paragraphs) <= 1 and len(body_text) < 90:
        kind = "title"
    elif len(body_paragraphs) >= 2 or len(body_text) >= 90:
        kind = "content"
    else:
        # a single short line under a heading on a later slide reads as a divider
        kind = "section" if index > 0 and len(body_text) < 60 else "content"

    info = SlideInfo(
        index=index,
        kind=kind,
        title_id=title.shape_id if title is not None else None,
        body_id=body.shape_id if body is not None else None,
        picture_ids=[p.shape_id for p in big_pictures],
        stale_ids=stale,
        complex=complex_,
        title_pt=resolve_pt(title, slide, True) if title is not None else 36,
        body_pt=resolve_pt(body, slide, False) if body is not None else 20,
        preview_text=(title.text_frame.text.strip()[:80] if title is not None else ""),
        role=_slide_role(title, rest),
        clutter=len(stale) + len(big_pictures),
    )
    return info


def _slide_role(title, others) -> str | None:
    """The heading names the role if it can; otherwise any label on the slide
    (e.g. a "Retrieval Practice:" box or a "Climate 1 'I do'" badge)."""
    if title is not None:
        role = role_of(_text(title))
        if role:
            return role
    for s in others:
        text = _text(s)
        if text and not is_lesson_label(text):
            role = role_of(text)
            if role:
                return role
    return None


def _repeated_images(prs) -> frozenset[str]:
    seen: Counter[str] = Counter()
    for slide in prs.slides:
        hashes = {_image_hash(s) for s in slide.shapes if _is_picture(s)}
        seen.update(h for h in hashes if h)
    return frozenset(h for h, n in seen.items() if n >= 2)


def analyze_presentation(prs) -> list[SlideInfo]:
    w, h = prs.slide_width, prs.slide_height
    repeated = _repeated_images(prs)
    return [analyze_slide(s, i, w, h, repeated) for i, s in enumerate(prs.slides)]


# --------------------------------------------------------------------------- #
# Capacity hints for the AI ("how much text fits in this style?")
# --------------------------------------------------------------------------- #
def content_capacity(prs, infos: list[SlideInfo]) -> dict:
    bullets, words = [], []
    for info in infos:
        if info.kind != "content" or info.body_id is None:
            continue
        shape = shape_by_id(prs.slides[info.index], info.body_id)
        if shape is None:
            continue
        w_pt = (shape.width or 0) / EMU_PER_PT - 28
        h_pt = (shape.height or 0) / EMU_PER_PT - 14
        pt = max(info.body_pt, 10)
        lines = max(h_pt / (pt * 1.25), 1)
        chars_per_line = max(w_pt / (pt * 0.5), 10)
        # Generous floors: the generator shrinks the font to fit, and a teacher's five
        # retrieval questions must never be squeezed into three.
        bullets.append(max(6, min(8, int(lines / 1.6))))
        words.append(max(14, min(25, int(chars_per_line * 1.5 / 6))))
    if not bullets:
        return {"max_bullets": 6, "max_words_per_bullet": 16}
    bullets.sort()
    words.sort()
    return {
        "max_bullets": bullets[len(bullets) // 2],
        "max_words_per_bullet": words[len(words) // 2],
    }


# --------------------------------------------------------------------------- #
# Style profile (what the UI shows on a style card)
# --------------------------------------------------------------------------- #
def _theme_xml(prs):
    try:
        master_part = prs.slide_master.part
        theme_part = master_part.part_related_by(RT.THEME)
        return etree.fromstring(theme_part.blob)
    except Exception:  # noqa: BLE001
        return None


_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _theme_colors_and_fonts(prs) -> tuple[dict[str, str], dict[str, str]]:
    root = _theme_xml(prs)
    colors: dict[str, str] = {}
    fonts: dict[str, str] = {}
    if root is None:
        return colors, fonts
    scheme = root.find(f".//{{{_A}}}clrScheme")
    if scheme is not None:
        for child in scheme:
            name = etree.QName(child).localname
            inner = child[0] if len(child) else None
            if inner is None:
                continue
            val = inner.get("val") if etree.QName(inner).localname == "srgbClr" else inner.get("lastClr")
            if val:
                colors[name] = val.upper()
    for key, tag in (("heading", "majorFont"), ("body", "minorFont")):
        latin = root.find(f".//{{{_A}}}{tag}/{{{_A}}}latin")
        if latin is not None and latin.get("typeface"):
            fonts[key] = latin.get("typeface")
    return colors, fonts


def _is_bright(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def extract_style_profile(path: Path) -> dict:
    prs = Presentation(str(path))
    infos = analyze_presentation(prs)
    theme_colors, theme_fonts = _theme_colors_and_fonts(prs)

    used_fonts: Counter[str] = Counter()
    used_colors: Counter[str] = Counter()
    backgrounds: Counter[str] = Counter()

    for slide in prs.slides:
        bg = slide._element.cSld.find(qn("p:bg"))
        if bg is not None:
            clr = bg.find(f".//{qn('a:srgbClr')}")
            if clr is not None:
                backgrounds[clr.get("val").upper()] += 1
            elif bg.find(f".//{qn('a:blip')}") is not None:
                backgrounds["image"] += 1
        for shape in slide.shapes:
            for node in shape._element.iter():
                tag = etree.QName(node).localname
                if tag == "latin" and node.get("typeface") and not node.get("typeface").startswith("+"):
                    used_fonts[node.get("typeface")] += 1
                elif tag == "srgbClr" and node.get("val"):
                    used_colors[node.get("val").upper()] += 1

    fonts: list[str] = []
    for name in [*(f for f, _ in used_fonts.most_common(3))]:
        fonts.append(name)
    for name in (theme_fonts.get("heading"), theme_fonts.get("body")):
        if name and name not in fonts and not name.startswith("+"):
            fonts.append(name)

    palette: list[str] = []
    for clr, _ in backgrounds.most_common(2):
        if clr != "image" and clr not in palette:
            palette.append(clr)
    for clr, _ in used_colors.most_common(6):
        if clr not in palette:
            palette.append(clr)
    for key in ("accent1", "accent2", "accent3", "dk2"):
        clr = theme_colors.get(key)
        if clr and clr not in palette:
            palette.append(clr)
    palette = palette[:6]

    dominant_bg = backgrounds.most_common(1)[0][0] if backgrounds else theme_colors.get("lt1", "FFFFFF")
    if dominant_bg == "image":
        tone = "image"
    else:
        tone = "dark" if _is_bright(dominant_bg) < 0.45 else "light"

    kinds = Counter(i.kind for i in infos)
    capacity = content_capacity(prs, infos)

    return {
        "slide_count": len(infos),
        "slide_size_in": [round(prs.slide_width / 914400, 2), round(prs.slide_height / 914400, 2)],
        "fonts": fonts[:4],
        "palette": palette,
        "background_tone": tone,
        "kinds": dict(kinds),
        "capacity": capacity,
        "exemplars": [i.to_dict() for i in infos],
        "layout_names": [l.name for l in prs.slide_layouts][:12],
    }


def style_roles(prs, infos: list[SlideInfo]) -> dict[str, dict[str, str]]:
    """Routine slides this style has, with an example heading each (for the AI prompt).

    When the role isn't in the heading (e.g. a retrieval slide headed "Nutrients
    24th Sep" whose body starts "Retrieval Practice:"), `label` holds that first
    body line so new slides can repeat it."""
    found: dict[str, dict[str, str]] = {}
    for info in infos:
        if not info.role or info.role in found or info.complex:
            continue
        slide = prs.slides[info.index]
        title = shape_by_id(slide, info.title_id) if info.title_id else None
        body = shape_by_id(slide, info.body_id) if info.body_id else None
        title_text = " ".join(_text(title).split())[:60] if title is not None else ""
        label = ""
        if role_of(title_text) is None and body is not None:
            first = next((p.text.strip() for p in body.text_frame.paragraphs if p.text.strip()), "")
            if role_of(first) == info.role and len(first) <= 40:
                label = first
        found[info.role] = {"title": title_text, "label": label}
    return found
