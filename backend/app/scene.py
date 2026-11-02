"""On-slide editing: describe a slide as movable pieces, and write edits back.

The editor shows a picture of the slide *without* its text boxes and pictures (the
"background": shapes, fills, logos that aren't editable stay in it), and draws the text
boxes and pictures on top as pieces the teacher can drag, resize and format. Saving
writes positions, sizes and text formatting into the .pptx itself.

Units: positions and sizes are EMU (914400 per inch), font sizes are points.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from .pptx_analysis import _ph_type, resolve_pt

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_FILLS = ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill")
_SCHEME_ALIAS = {"tx1": "dk1", "bg1": "lt1", "tx2": "dk2", "bg2": "lt2"}
_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------- #
# Colours and fonts
# --------------------------------------------------------------------------- #
def _theme_colors(slide) -> dict[str, str]:
    master = slide.slide_layout.slide_master
    for rel in master.part.rels.values():
        if rel.reltype.endswith("/theme"):
            root = etree.fromstring(rel.target_part.blob)
            scheme = root.find(f".//{{{A}}}clrScheme")
            colors = {}
            for child in scheme if scheme is not None else []:
                name = etree.QName(child).localname
                srgb = child.find(f"{{{A}}}srgbClr")
                sys_clr = child.find(f"{{{A}}}sysClr")
                if srgb is not None:
                    colors[name] = srgb.get("val")
                elif sys_clr is not None:
                    colors[name] = sys_clr.get("lastClr") or "000000"
            return colors
    return {}


def _color_of(fill_parent, theme: dict[str, str]) -> str | None:
    """'#RRGGBB' for an element holding <a:solidFill>, if it can be resolved."""
    if fill_parent is None:
        return None
    solid = fill_parent.find(qn("a:solidFill"))
    if solid is None:
        return None
    srgb = solid.find(qn("a:srgbClr"))
    if srgb is not None and srgb.get("val"):
        return "#" + srgb.get("val").upper()
    scheme = solid.find(qn("a:schemeClr"))
    if scheme is not None:
        name = _SCHEME_ALIAS.get(scheme.get("val"), scheme.get("val"))
        if name in theme:
            return "#" + theme[name].upper()
    return None


# --------------------------------------------------------------------------- #
# Which shapes are editable
# --------------------------------------------------------------------------- #
def _is_picture(shape) -> bool:
    return shape.shape_type == MSO_SHAPE_TYPE.PICTURE or shape._element.tag == qn("p:pic")


def editable_shapes(slide, slide_w: int, slide_h: int) -> list:
    """Top-level text boxes with text, and pictures. Full-slide background pictures,
    groups, tables and charts stay part of the background."""
    out = []
    for shape in slide.shapes:
        if None in (shape.left, shape.top, shape.width, shape.height):
            continue
        if _is_picture(shape):
            if shape.width * shape.height < 0.85 * slide_w * slide_h:
                out.append(shape)
        elif shape.has_text_frame and shape.text_frame.text.strip():
            out.append(shape)
    return out


def _fill_css(sp_pr, theme) -> str | None:
    """CSS colour for a shape's solid fill, honouring transparency (<a:alpha>)."""
    colour = _color_of(sp_pr, theme)
    if not colour:
        return None
    solid = sp_pr.find(qn("a:solidFill"))
    clr = next(iter(solid), None) if solid is not None else None
    alpha_el = clr.find(qn("a:alpha")) if clr is not None else None
    alpha = int(alpha_el.get("val", "100000")) / 100000 if alpha_el is not None else 1.0
    if alpha <= 0.01:
        return None  # fully transparent: no fill
    if alpha >= 0.99:
        return colour
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def _box_fill(shape, theme) -> tuple[str | None, bool]:
    """(CSS fill, frame_is_fixed). A text box with no fill or a solid fill can move as a
    whole; one whose look comes from a style/gradient keeps its frame in the background."""
    sp_pr = shape._element.find(qn("p:spPr"))
    if sp_pr is not None and sp_pr.find(qn("a:noFill")) is not None:
        return None, False
    if sp_pr is not None and sp_pr.find(qn("a:solidFill")) is not None:
        return _fill_css(sp_pr, theme), False
    if sp_pr is not None and any(sp_pr.find(qn(t)) is not None for t in ("a:gradFill", "a:blipFill", "a:pattFill")):
        return None, True
    style = shape._element.find(qn("p:style"))
    fill_ref = style.find(qn("a:fillRef")) if style is not None else None
    if fill_ref is not None and fill_ref.get("idx") not in (None, "0"):
        return None, True
    return None, False


# --------------------------------------------------------------------------- #
# Reading text with its formatting
# --------------------------------------------------------------------------- #
def _font_scale(shape) -> float:
    body = shape.text_frame._txBody.find(qn("a:bodyPr"))
    norm = body.find(qn("a:normAutofit")) if body is not None else None
    if norm is not None and norm.get("fontScale"):
        return int(norm.get("fontScale")) / 100000
    return 1.0


def _run_props(rpr, defaults: dict, theme) -> dict:
    """Effective look of a run: its own settings, falling back to the paragraph's."""
    props = dict(defaults)
    if rpr is None:
        return props
    if rpr.get("sz"):
        props["size"] = int(rpr.get("sz")) / 100
    if rpr.get("b") is not None:
        props["bold"] = rpr.get("b") in ("1", "true")
    if rpr.get("i") is not None:
        props["italic"] = rpr.get("i") in ("1", "true")
    if rpr.get("u") is not None:
        props["underline"] = rpr.get("u") not in ("none", "")
    colour = _color_of(rpr, theme)
    if colour:
        props["color"] = colour
    latin = rpr.find(qn("a:latin"))
    if latin is not None and latin.get("typeface") and not latin.get("typeface").startswith("+"):
        props["font"] = latin.get("typeface")
    return props


def _shape_defaults(shape, slide, theme) -> dict:
    is_title = _ph_type(shape) is not None and "TITLE" in str(_ph_type(shape))
    return {
        "size": resolve_pt(shape, slide, is_title),
        "bold": False,
        "italic": False,
        "underline": False,
        "color": "#" + theme.get("dk1", "000000").upper(),
        "font": None,
    }


def _para_defaults(p, base: dict, theme) -> dict:
    ppr = p.find(qn("a:pPr"))
    defrpr = ppr.find(qn("a:defRPr")) if ppr is not None else None
    end = p.find(qn("a:endParaRPr"))
    props = _run_props(defrpr, base, theme)
    # An empty paragraph only has endParaRPr: it says how its (future) text looks.
    if not p.findall(qn("a:r")) and end is not None:
        props = _run_props(end, props, theme)
    return props


def _paragraph_model(p, base: dict, theme, scale: float) -> dict:
    ppr = p.find(qn("a:pPr"))
    defaults = _para_defaults(p, base, theme)
    runs = []
    for child in p:
        tag = etree.QName(child).localname
        if tag in ("r", "fld"):
            t = child.find(qn("a:t"))
            props = _run_props(child.find(qn("a:rPr")), defaults, theme)
            runs.append({"text": (t.text or "") if t is not None else "", **props})
        elif tag == "br":
            runs.append({"text": "\n", **defaults})
    for r in runs:
        r["size"] = round(r["size"] * scale, 2)
    bullet = None
    if ppr is not None:
        if ppr.find(qn("a:buChar")) is not None:
            bullet = ppr.find(qn("a:buChar")).get("char") or "•"
        elif ppr.find(qn("a:buAutoNum")) is not None:
            bullet = "#"
    return {
        "align": (ppr.get("algn") if ppr is not None else None) or "l",
        "level": int(ppr.get("lvl", 0)) if ppr is not None else 0,
        "bullet": bullet,
        "runs": runs or [{"text": "", **{**defaults, "size": round(defaults["size"] * scale, 2)}}],
    }


def describe_slide(pptx_path: Path, number: int) -> dict:
    """Everything the editor needs to draw slide `number` (1-based) as movable pieces."""
    prs = Presentation(str(pptx_path))
    if not 1 <= number <= len(prs.slides):
        raise IndexError(number)
    slide = prs.slides[number - 1]
    sw, sh = prs.slide_width, prs.slide_height
    theme = _theme_colors(slide)
    shapes = []
    for shape in editable_shapes(slide, sw, sh):
        item = {
            "id": shape.shape_id,
            "x": int(shape.left), "y": int(shape.top), "w": int(shape.width), "h": int(shape.height),
            "rotation": float(getattr(shape, "rotation", 0) or 0),
        }
        if _is_picture(shape):
            item.update(kind="picture", fixed=False)
        else:
            fill, fixed = _box_fill(shape, theme)
            sp_pr = shape._element.find(qn("p:spPr"))
            ln = sp_pr.find(qn("a:ln")) if sp_pr is not None else None
            border = None
            if ln is not None and ln.find(qn("a:noFill")) is None:
                ln_colour = _color_of(ln, theme)
                if ln_colour:
                    border = {"color": ln_colour, "width": int(ln.get("w", 9525))}
            body = shape.text_frame._txBody.find(qn("a:bodyPr"))
            get = (lambda k, d: int(body.get(k, d))) if body is not None else (lambda k, d: d)
            base = _shape_defaults(shape, slide, theme)
            scale = _font_scale(shape)
            item.update(
                kind="text",
                fixed=fixed,
                fill=fill,
                border=border,
                anchor=(body.get("anchor") if body is not None else None) or ("ctr" if _ph_type(shape) and "TITLE" in str(_ph_type(shape)) else "t"),
                insets={"l": get("lIns", 91440), "t": get("tIns", 45720), "r": get("rIns", 91440), "b": get("bIns", 45720)},
                paragraphs=[_paragraph_model(p, base, theme, scale) for p in shape.text_frame._txBody.findall(qn("a:p"))],
            )
        shapes.append(item)
    return {"number": number, "count": len(prs.slides), "width": int(sw), "height": int(sh), "shapes": shapes}


# --------------------------------------------------------------------------- #
# Background: the slide without its editable pieces
# --------------------------------------------------------------------------- #
def background_deck(pptx_path: Path, number: int, out_path: Path) -> None:
    """A one-slide copy of slide `number` with its editable pieces taken out. Text boxes
    whose frame stays (style/gradient fills) keep the frame; only their text goes."""
    prs = Presentation(str(pptx_path))
    ids = prs.slides._sldIdLst
    for i, sld_id in reversed(list(enumerate(list(ids), 1))):
        if i != number:
            prs.part.drop_rel(sld_id.rId)
            ids.remove(sld_id)
    slide = prs.slides[0]
    theme = _theme_colors(slide)
    for shape in editable_shapes(slide, prs.slide_width, prs.slide_height):
        if not _is_picture(shape) and _box_fill(shape, theme)[1]:
            for t in shape.text_frame._txBody.iter(qn("a:t")):
                t.text = ""
        else:
            shape._element.getparent().remove(shape._element)
    prs.save(str(out_path))


def picture_bytes(pptx_path: Path, number: int, shape_id: int) -> tuple[bytes, str]:
    prs = Presentation(str(pptx_path))
    slide = prs.slides[number - 1]
    for shape in slide.shapes:
        if shape.shape_id == shape_id and _is_picture(shape):
            return shape.image.blob, shape.image.content_type
    raise KeyError(shape_id)


# --------------------------------------------------------------------------- #
# Writing edits back
# --------------------------------------------------------------------------- #
def _set_run_color(rpr, hex_color: str) -> None:
    for tag in _FILLS:
        for el in rpr.findall(qn(tag)):
            rpr.remove(el)
    solid = etree.Element(qn("a:solidFill"))
    etree.SubElement(solid, qn("a:srgbClr")).set("val", hex_color.lstrip("#").upper())
    ln = rpr.find(qn("a:ln"))
    if ln is not None:
        ln.addnext(solid)
    else:
        rpr.insert(0, solid)


def _apply_run(rpr, wanted: dict, current: dict) -> None:
    """Write only what the teacher changed, so untouched text keeps theme colours etc."""
    size = wanted.get("size")
    if isinstance(size, (int, float)) and abs(size - current["size"]) >= 0.25:
        rpr.set("sz", str(int(round(max(4, min(400, size)) * 100))))
    for key, attr in (("bold", "b"), ("italic", "i")):
        if key in wanted and bool(wanted[key]) != current[key]:
            rpr.set(attr, "1" if wanted[key] else "0")
    if "underline" in wanted and bool(wanted["underline"]) != current["underline"]:
        rpr.set("u", "sng" if wanted["underline"] else "none")
    colour = wanted.get("color")
    if isinstance(colour, str) and _HEX.match(colour) and colour.upper().lstrip("#") != current["color"].upper().lstrip("#"):
        _set_run_color(rpr, colour)


def _rewrite_text(shape, slide, paragraphs: list[dict], theme) -> None:
    tx = shape.text_frame._txBody
    originals = tx.findall(qn("a:p"))
    base = _shape_defaults(shape, slide, theme)
    scale = _font_scale(shape)
    for p in originals:
        tx.remove(p)
    for i, para in enumerate(paragraphs or [{"runs": [{"text": ""}]}]):
        template = originals[min(i, len(originals) - 1)] if originals else etree.Element(qn("a:p"))
        defaults = _para_defaults(template, base, theme)
        first_run = template.find(qn("a:r"))
        rpr_template = first_run.find(qn("a:rPr")) if first_run is not None else None
        if rpr_template is None:
            end = template.find(qn("a:endParaRPr"))
            rpr_template = copy.deepcopy(end) if end is not None else etree.Element(qn("a:rPr"))
            rpr_template.tag = qn("a:rPr")
        current = _run_props(rpr_template, defaults, theme)  # stored size, before auto-shrink

        p = copy.deepcopy(template)
        for child in list(p):
            if etree.QName(child).localname in ("r", "br", "fld"):
                p.remove(child)
        end = p.find(qn("a:endParaRPr"))
        for run in para.get("runs") or []:
            text = str(run.get("text", ""))
            if not text:
                continue
            for k, piece in enumerate(text.split("\n")):
                if k:
                    br = etree.Element(qn("a:br"))
                    br.append(copy.deepcopy(rpr_template))
                    (end.addprevious(br) if end is not None else p.append(br))
                if not piece:
                    continue
                r = etree.Element(qn("a:r"))
                rpr = copy.deepcopy(rpr_template)
                for link in rpr.findall(qn("a:hlinkClick")):
                    rpr.remove(link)
                # Sizes arrive as shown on screen; a box that auto-shrinks its text shows it
                # at `scale` of the stored size, so convert back before comparing.
                wanted = dict(run)
                if isinstance(wanted.get("size"), (int, float)) and scale:
                    wanted["size"] = wanted["size"] / scale
                _apply_run(rpr, wanted, current)
                r.append(rpr)
                etree.SubElement(r, qn("a:t")).text = piece
                (end.addprevious(r) if end is not None else p.append(r))
        tx.append(p)


def apply_edits(pptx_path: Path, number: int, edits: list[dict]) -> int:
    """Apply the editor's changes to slide `number`. Returns how many shapes changed."""
    prs = Presentation(str(pptx_path))
    if not 1 <= number <= len(prs.slides):
        raise IndexError(number)
    slide = prs.slides[number - 1]
    sw, sh = prs.slide_width, prs.slide_height
    theme = _theme_colors(slide)
    by_id = {s.shape_id: s for s in editable_shapes(slide, sw, sh)}
    changed = 0
    for edit in edits:
        shape = by_id.get(edit.get("id"))
        if shape is None:
            continue
        for key, attr in (("x", "left"), ("y", "top"), ("w", "width"), ("h", "height")):
            value = edit.get(key)
            if isinstance(value, (int, float)):
                limit = sw if key in ("x", "w") else sh
                value = int(max(-limit, min(2 * limit, value)))
                if key in ("w", "h"):
                    value = max(91440 // 4, value)
                setattr(shape, attr, value)
        if "paragraphs" in edit and not _is_picture(shape) and shape.has_text_frame:
            _rewrite_text(shape, slide, edit["paragraphs"], theme)
        changed += 1
    prs.save(str(pptx_path))
    return changed
