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
    clutter: float = 0  # share of the slide covered by decoration left once sample content is gone
    title_pt: float = 36
    body_pt: float = 20
    preview_text: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "has_title": self.title_id is not None,
            "has_body": self.body_id is not None,
            "pictures": len(self.picture_ids),
            "complex": self.complex,
            "clutter": self.clutter,
            "preview_text": self.preview_text,
        }


# --------------------------------------------------------------------------- #
# Shape helpers
# --------------------------------------------------------------------------- #
def _walk(shapes, top=None):
    """Every shape on a slide, inside groups too, paired with its top-level ancestor."""
    for shp in shapes:
        root = top if top is not None else shp
        yield shp, root
        if shp.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(shp.shapes, root)


def shape_by_id(slide: Slide, shape_id: int):
    for shp, _ in _walk(slide.shapes):
        if shp.shape_id == shape_id:
            return shp
    return None


def _box(shape) -> tuple[int, int, int, int]:
    left, top = shape.left or 0, shape.top or 0
    return left, top, left + (shape.width or 0), top + (shape.height or 0)


def _touches(a: tuple[int, int, int, int], b: tuple[int, int, int, int], pad: int = 0) -> bool:
    return a[0] - pad < b[2] and b[0] - pad < a[2] and a[1] - pad < b[3] and b[1] - pad < a[3]


def _norm_text(text: str) -> str:
    return " ".join(text.split()).lower()


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
    slide: Slide,
    index: int,
    slide_w: int,
    slide_h: int,
    repeated: frozenset[str] = frozenset(),
    repeated_text: frozenset[str] = frozenset(),
) -> SlideInfo:
    slide_area = slide_w * slide_h
    walked = list(_walk(slide.shapes))
    top_of = {s.shape_id: root for s, root in walked}
    text_shapes = [s for s, _ in walked if _is_text_candidate(s)]
    # "Content" pictures are big but not decoration. Full-bleed backgrounds and anything
    # repeated across slides (logos, banners, corner art) are part of the style: keep them.
    big_pictures = [
        s
        for s in slide.shapes
        if _is_picture(s)
        and 0.10 * slide_area < _area(s) < 0.85 * slide_area
        and _image_hash(s) not in repeated
    ]
    tables_and_charts = [
        s
        for s, _ in walked
        if s.shape_type in (MSO_SHAPE_TYPE.TABLE, MSO_SHAPE_TYPE.CHART)
        or getattr(s, "has_table", False)
        or getattr(s, "has_chart", False)
    ]
    complex_ = bool(tables_and_charts)

    # --- title ---------------------------------------------------------- #
    title_phs = [s for s in text_shapes if _ph_type(s) in _TITLE_PLACEHOLDERS]
    title = next((s for s in title_phs if s.text_frame.text.strip()), title_phs[0] if title_phs else None)
    if title is None and text_shapes:
        # biggest font wins; ties broken by position (higher on the slide first)
        title = sorted(
            text_shapes,
            key=lambda s: (-resolve_pt(s, slide, True), s.top or 0, s.left or 0),
        )[0]

    # --- body ----------------------------------------------------------- #
    rest = [s for s in text_shapes if s is not title]
    body = next((s for s in rest if _ph_type(s) in _SUBTITLE_PLACEHOLDERS), None)
    body_candidates = [s for s in rest if s.text_frame.text.strip() or s.is_placeholder]
    if body is None and body_candidates:
        body = sorted(body_candidates, key=lambda s: -_area(s))[0]

    # Any other text is sample content and gets removed later, unless it is style:
    # text repeated across sample slides (school name, running footer). Footer, date
    # and slide-number placeholders never reach `rest`, so they always stay.
    def is_style(s) -> bool:
        return _norm_text(s.text_frame.text) in repeated_text

    leftovers = [s for s in rest if s is not body and s.text_frame.text.strip() and not is_style(s)]
    # Pictures that aren't style (repeated logo, full-bleed background) and aren't the
    # image slot are sample content too: icons, screenshots, diagrams.
    leftovers += [
        s
        for s, _ in walked
        if _is_picture(s) and s not in big_pictures
        and _image_hash(s) not in repeated and _area(s) < 0.85 * slide_area
    ]
    # A group holding only sample text (a callout and its box) goes as a whole;
    # one that also holds the title, body or style text just loses that text.
    keep_groups = {top_of[s.shape_id].shape_id for s in (title, body) if s is not None}
    keep_groups |= {top_of[s.shape_id].shape_id for s in rest if s.text_frame.text.strip() and is_style(s)}
    stale: list[int] = []
    for s in [*leftovers, *tables_and_charts]:
        root = top_of[s.shape_id]
        sid = s.shape_id if root is s or root.shape_id in keep_groups else root.shape_id
        if sid not in stale:
            stale.append(sid)

    kept_roots = {top_of[s.shape_id].shape_id for s in (title, body) if s is not None}
    # Frames, bars and lines that held sample content would be left empty: drop the ones
    # touching removed content, as long as they don't touch the title, body or image slot.
    kept_boxes = [_box(s) for s in (title, body, *big_pictures) if s is not None]
    removed_boxes = [_box(s) for s, _ in walked if s.shape_id in stale]
    frames = [
        s for s in slide.shapes
        if not s.is_placeholder and not _is_picture(s) and s.shape_id not in stale
        and s.shape_id not in kept_roots and s.shape_type != MSO_SHAPE_TYPE.GROUP
        and _area(s) < 0.5 * slide_area
        and not (s.has_text_frame and s.text_frame.text.strip())
    ]
    pad = 91440  # 0.1 inch: a bar drawn beside its card still counts as touching it
    changed = True
    while changed:
        changed = False
        for f in frames:
            box = _box(f)
            if f.shape_id in stale or any(_touches(box, k) for k in kept_boxes):
                continue
            if any(_touches(box, r, pad) for r in removed_boxes):
                stale.append(f.shape_id)
                removed_boxes.append(box)
                changed = True

    # Shapes that stay on a clone but carry nothing of the teacher's new slide: empty
    # cards, bars and divider lines that framed sample content, on the slide or built
    # into its layout. Style (backgrounds, logos, repeated text, footers) doesn't count.
    def is_decor(s) -> bool:
        if s.is_placeholder or (s.part is slide.part and (s.shape_id in kept_roots or s.shape_id in gone)):
            return False
        if _area(s) >= 0.85 * slide_area:
            return False
        if _is_picture(s):  # sample pictures are removed; artwork baked into a layout stays
            return s.part is not slide.part and _area(s) >= 0.05 * slide_area
        return not (s.has_text_frame and s.text_frame.text.strip() and is_style(s))

    gone = set(stale) | {p.shape_id for p in big_pictures}
    decor = [s for s in slide.shapes if is_decor(s)] + [s for s in slide.slide_layout.shapes if is_decor(s)]
    # Lines have next to no area but still stand out on an empty slide.
    clutter = min(sum(max(_area(s), 0.01 * slide_area) for s in decor) / slide_area, 1.0)

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
        clutter=clutter,
        title_pt=resolve_pt(title, slide, True) if title is not None else 36,
        body_pt=resolve_pt(body, slide, False) if body is not None else 20,
        preview_text=(title.text_frame.text.strip()[:80] if title is not None else ""),
    )
    return info


def _style_threshold(prs) -> int:
    """Style (logo, footer) shows on most sample slides; an icon reused on a couple doesn't."""
    return max(2, math.ceil(len(prs.slides) / 2))


def _repeated_images(prs) -> frozenset[str]:
    seen: Counter[str] = Counter()
    for slide in prs.slides:
        hashes = {_image_hash(s) for s, _ in _walk(slide.shapes) if _is_picture(s)}
        seen.update(h for h in hashes if h)
    return frozenset(h for h, n in seen.items() if n >= _style_threshold(prs))


def _repeated_texts(prs) -> frozenset[str]:
    seen: Counter[str] = Counter()
    for slide in prs.slides:
        texts = {_norm_text(s.text_frame.text) for s, _ in _walk(slide.shapes) if s.has_text_frame}
        seen.update(t for t in texts if t)
    return frozenset(t for t, n in seen.items() if n >= _style_threshold(prs))


def _layout_pictures(slide: Slide) -> int:
    return sum(1 for _ in slide.slide_layout._element.iter(qn("a:blip")))


def analyze_presentation(prs) -> list[SlideInfo]:
    w, h = prs.slide_width, prs.slide_height
    repeated = _repeated_images(prs)
    repeated_text = _repeated_texts(prs)
    infos = [analyze_slide(s, i, w, h, repeated, repeated_text) for i, s in enumerate(prs.slides)]

    # Cover designs only make covers: the first sample, and any sample whose layout is
    # dressed with several more pictures than usual (partner logos, cover art), would
    # put that artwork on every ordinary slide cloned from it.
    counts = [_layout_pictures(s) for s in prs.slides]
    usual = sorted(counts)[len(counts) // 2] if counts else 0
    for info, n in zip(infos, counts):
        dressed = n - usual >= 3
        if info.kind in ("content", "image") and info.title_id is not None and (info.index == 0 or dressed):
            info.kind = "title"
    return infos


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
        bullets.append(max(3, min(7, int(lines / 1.6))))
        words.append(max(8, min(18, int(chars_per_line * 1.5 / 6))))
    if not bullets:
        return {"max_bullets": 5, "max_words_per_bullet": 14}
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
