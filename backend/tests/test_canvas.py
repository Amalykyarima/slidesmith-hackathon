"""On-slide editing: read a slide as movable pieces, then save moves, resizes and
text formatting into the .pptx."""
import io
from pathlib import Path

from fastapi.testclient import TestClient
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app import config, scene
from app.main import app

FIX = Path(__file__).parent / "fixtures"


def _deck(tmp_path) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    head = s.shapes.add_textbox(Inches(0.3), Inches(0.2), Inches(9), Inches(0.7))
    r = head.text_frame.paragraphs[0].add_run()
    r.text = "What is alcohol?"
    r.font.size = Pt(32)
    r.font.bold = True
    body = s.shapes.add_textbox(Inches(0.5), Inches(1.2), Inches(5), Inches(3))
    for i, line in enumerate(["It is a depressant.", "The liver breaks it down."]):
        p = body.text_frame.paragraphs[0] if i == 0 else body.text_frame.add_paragraph()
        run = p.add_run()
        run.text = line
        run.font.size = Pt(24)
    clear = s.shapes.add_textbox(Inches(0.5), Inches(4.4), Inches(5), Inches(0.6))
    clear.text_frame.text = "Transparent box"
    sp_pr = clear._element.find(qn("p:spPr"))
    solid = etree.SubElement(sp_pr, qn("a:solidFill"))
    clr = etree.SubElement(solid, qn("a:srgbClr"))
    clr.set("val", "000000")
    etree.SubElement(clr, qn("a:alpha")).set("val", "0")
    img = tmp_path / "liver.png"
    Image.new("RGB", (300, 200), "#aa4444").save(img)
    s.shapes.add_picture(str(img), Inches(6), Inches(1.2), Inches(3), Inches(2))
    path = tmp_path / "canvas.pptx"
    prs.save(path)
    return path


def test_describe_slide(tmp_path):
    model = scene.describe_slide(_deck(tmp_path), 1)
    assert model["width"] == Inches(10) and model["count"] == 1
    kinds = [(s["kind"], s.get("fill")) for s in model["shapes"]]
    assert kinds == [("text", None), ("text", None), ("text", None), ("picture", None)]  # alpha 0 = no fill
    head = model["shapes"][0]["paragraphs"][0]["runs"][0]
    assert head["text"] == "What is alcohol?" and head["size"] == 32 and head["bold"] is True
    body = model["shapes"][1]
    assert [p["runs"][0]["text"] for p in body["paragraphs"]] == ["It is a depressant.", "The liver breaks it down."]


def test_background_has_no_editable_pieces(tmp_path):
    out = tmp_path / "bg.pptx"
    scene.background_deck(_deck(tmp_path), 1, out)
    slide = Presentation(str(out)).slides[0]
    assert not any(sh.has_text_frame and sh.text_frame.text.strip() for sh in slide.shapes)
    assert not any(sh.shape_type == 13 for sh in slide.shapes)


def test_apply_edits_moves_resizes_and_formats_only_what_changed(tmp_path):
    path = _deck(tmp_path)
    model = scene.describe_slide(path, 1)
    head, body, _, pic = model["shapes"]
    keep = lambda r: {k: r[k] for k in ("text", "size", "color", "bold", "italic", "underline")}  # noqa: E731
    first = keep(body["paragraphs"][0]["runs"][0])
    scene.apply_edits(path, 1, [
        {"id": body["id"], "x": body["x"] + Inches(4), "paragraphs": [
            {"runs": [first]},
            {"runs": [{**first, "text": "The "}, {**first, "text": "liver", "bold": True, "italic": True,
                                                  "underline": True, "color": "#C00000", "size": 36},
                      {**first, "text": " breaks it down."}]},
            {"runs": [{**first, "text": "A new line typed in the editor."}]},
        ]},
        {"id": pic["id"], "x": Inches(0.5), "y": Inches(3.5), "w": Inches(1.5), "h": Inches(1)},
        {"id": 9999, "x": 0},  # unknown shapes are ignored
    ])
    prs = Presentation(str(path))
    shapes = {s.shape_id: s for s in prs.slides[0].shapes}
    b, p = shapes[body["id"]], shapes[pic["id"]]
    assert b.left == body["x"] + Inches(4) and b.top == body["y"]
    assert (p.left, p.top, p.width, p.height) == (Inches(0.5), Inches(3.5), Inches(1.5), Inches(1))
    paras = b.text_frame.paragraphs
    assert [pp.text for pp in paras] == ["It is a depressant.", "The liver breaks it down.", "A new line typed in the editor."]
    liver = paras[1].runs[1]
    assert (liver.font.bold, liver.font.italic, liver.font.underline) == (True, True, True)
    assert liver.font.size == Pt(36) and liver.font.color.rgb == RGBColor(0xC0, 0, 0)
    plain = paras[1].runs[0]._r.find(qn("a:rPr"))
    assert plain.find(qn("a:solidFill")) is None and plain.get("b") is None  # untouched: nothing forced
    assert shapes[head["id"]].text_frame.text == "What is alcohol?"


def test_editing_api(monkeypatch):
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        image_id = c.post("/api/images", files={"file": ("c.png", (FIX / "sample_diagram.png").read_bytes())}).json()["id"]
        gen = c.post("/api/build", json={"style_id": style["id"], "slides": [
            {"page": 1, "title": "Alcohol", "kind": "title"},
            {"page": 2, "kind": "image", "title": "The liver", "bullets": ["It breaks down alcohol."], "image_id": image_id},
        ]}).json()
        assert gen["rev"] == 0

        s = c.get(f"/api/generations/{gen['id']}/slides/2").json()
        assert s["number"] == 2 and s["count"] == 2
        url = s["background"] or c.get(f"/api/generations/{gen['id']}/slides/2/background").json()["background"]
        if url:  # drawn when LibreOffice is installed
            bg = c.get(url)
            assert bg.status_code == 200 and bg.headers["content-type"] == "image/jpeg"
        pictures = [x for x in s["shapes"] if x["kind"] == "picture"]
        texts = [x for x in s["shapes"] if x["kind"] == "text"]
        assert pictures and texts
        img = c.get(pictures[0]["src"])
        assert img.status_code == 200 and img.headers["content-type"].startswith("image/")

        title = next(t for t in texts if "liver" in t["paragraphs"][0]["runs"][0]["text"].lower())
        r = c.post(f"/api/generations/{gen['id']}/slides/2", json={"shapes": [
            {"id": title["id"], "x": title["x"] + 500000},
            {"id": pictures[0]["id"], "w": pictures[0]["w"] // 2, "h": pictures[0]["h"] // 2},
        ]})
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["rev"] == 1
        after = c.get(f"/api/generations/{gen['id']}").json()
        if after["previews"]:  # only the edited slide's thumbnail is redrawn
            assert after["previews"][0].endswith("?v=0") and after["previews"][1].endswith("?v=1")
            assert after["updating"] == [] and after["preview_status"] == "ready"
        deck = Presentation(io.BytesIO(c.get(new["download_url"]).content))
        moved = {sh.shape_id: sh for sh in deck.slides[1].shapes}
        assert moved[title["id"]].left == title["x"] + 500000
        assert moved[pictures[0]["id"]].width == pictures[0]["w"] // 2

        assert c.get(f"/api/generations/{gen['id']}/slides/9").status_code == 404
        assert c.post(f"/api/generations/{gen['id']}/slides/9", json={"shapes": []}).status_code == 404
        assert c.get("/api/generations/nope/slides/1").status_code == 404


def test_editing_is_per_teacher(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_CODES", {"maple-42": "Zoey", "river-7": "Mr Lee"})
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    with TestClient(app) as zoey, TestClient(app) as lee:
        zoey.post("/api/login", json={"code": "maple-42"})
        lee.post("/api/login", json={"code": "river-7"})
        style = zoey.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        gen = zoey.post("/api/build", json={"style_id": style["id"], "slides": [{"page": 1, "title": "Mine"}]}).json()
        assert zoey.get(f"/api/generations/{gen['id']}/slides/1").status_code == 200
        assert lee.get(f"/api/generations/{gen['id']}/slides/1").status_code == 404
        assert lee.post(f"/api/generations/{gen['id']}/slides/1", json={"shapes": []}).status_code == 404
