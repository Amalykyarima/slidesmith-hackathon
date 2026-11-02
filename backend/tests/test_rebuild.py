"""Editing a generated deck: change text, reorder, delete, pick another layout, swap the
picture, then rebuild (no AI). Previews get a new version so browsers refresh them."""
import io
from pathlib import Path

from fastapi.testclient import TestClient
from pptx import Presentation

from app import ai, config
from app.main import app

FIX = Path(__file__).parent / "fixtures"


def _texts(deck_bytes: bytes) -> list[str]:
    prs = Presentation(io.BytesIO(deck_bytes))
    return [" ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in prs.slides]


def test_edit_and_rebuild(monkeypatch):
    monkeypatch.setattr(ai, "generate_content", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI")))
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        samples = c.get(f"/api/styles/{style['id']}/samples").json()
        assert samples and {"index", "number", "kind", "role", "title", "preview"} <= set(samples[0])

        gen = c.post("/api/build", json={"style_id": style["id"], "title": "Alcohol", "slides": [
            {"page": 1, "title": "Alcohol 5th Nov 2026", "kind": "title"},
            {"page": 2, "title": "What is alcohol?", "bullets": ["Ethanol", "A depressant"]},
            {"page": 3, "title": "Short-term effects", "bullets": ["Slower reactions"]},
        ]}).json()
        assert gen["rev"] == 0
        assert all(isinstance(s["sample"], int) for s in gen["slides"])  # layout used is recorded

        image_id = c.post("/api/images", files={"file": ("liver.png", (FIX / "sample_diagram.png").read_bytes())}).json()["id"]
        slides = gen["slides"]
        edited = [
            {**slides[0], "page": 1},
            {**slides[2], "page": 2, "title": "Short-term effects", "bullets": ["Slower reactions", "Poor judgement"]},
            {**slides[1], "page": 3, "bullets": ["The alcohol in drinks is ethanol."], "image_id": image_id},
            {"page": 4, "title": "New slide", "bullets": ["Added in the editor"], "sample": slides[1]["sample"]},
        ]
        r = c.post(f"/api/generations/{gen['id']}/rebuild", json={"title": "Alcohol (edited)", "slides": edited})
        assert r.status_code == 200, r.text
        new = r.json()
        assert new["id"] == gen["id"] and new["rev"] == 1 and new["title"] == "Alcohol (edited)"
        assert [s["title"] for s in new["slides"]] == ["Alcohol 5th Nov 2026", "Short-term effects", "What is alcohol?", "New slide"]
        assert new["slides"][2]["image_id"] == image_id
        assert new["slides"][3]["sample"] == slides[1]["sample"]  # the chosen layout was used

        texts = _texts(c.get(new["download_url"]).content)
        assert len(texts) == 4
        assert "Poor judgement" in texts[1] and "The alcohol in drinks is ethanol." in texts[2]
        assert "Added in the editor" in texts[3]
        prs = Presentation(io.BytesIO(c.get(new["download_url"]).content))
        assert any(sh.shape_type == 13 for sh in prs.slides[2].shapes)  # the new picture

        # deleting a slide = sending fewer slides
        fewer = c.post(f"/api/generations/{gen['id']}/rebuild", json={"slides": [{**new["slides"][0], "page": 1}]}).json()
        assert fewer["rev"] == 2 and len(fewer["slides"]) == 1 and fewer["title"] == "Alcohol (edited)"
        assert len(_texts(c.get(fewer["download_url"]).content)) == 1

        bad = c.post(f"/api/generations/{gen['id']}/rebuild", json={"slides": [{"page": 1, "title": "a"}, {"page": 1, "title": "b"}]})
        assert bad.status_code == 400
        assert c.post("/api/generations/nope/rebuild", json={"slides": [{"page": 1, "title": "a"}]}).status_code == 404


def test_previews_get_a_new_version_after_rebuild():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        gen = c.post("/api/build", json={"style_id": style["id"], "slides": [{"page": 1, "title": "One"}]}).json()
        row_before = gen["previews"]
        new = c.post(f"/api/generations/{gen['id']}/rebuild", json={"slides": [{"page": 1, "title": "Two"}]}).json()
        assert all(u.endswith("?v=1") for u in new["previews"]) and all(u.endswith("?v=0") for u in row_before)


def test_rebuild_is_per_teacher(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_CODES", {"maple-42": "Zoey", "river-7": "Mr Lee"})
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    with TestClient(app) as zoey, TestClient(app) as lee:
        zoey.post("/api/login", json={"code": "maple-42"})
        lee.post("/api/login", json={"code": "river-7"})
        style = zoey.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        gen = zoey.post("/api/build", json={"style_id": style["id"], "slides": [{"page": 1, "title": "Mine"}]}).json()
        assert lee.post(f"/api/generations/{gen['id']}/rebuild", json={"slides": [{"page": 1, "title": "x"}]}).status_code == 404
        assert lee.get(f"/api/styles/{style['id']}/samples").status_code == 404
        assert zoey.post(f"/api/generations/{gen['id']}/rebuild", json={"slides": [{"page": 1, "title": "Still mine"}]}).status_code == 200
