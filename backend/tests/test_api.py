import io
import os
import tempfile
from pathlib import Path


from fastapi.testclient import TestClient  # noqa: E402
from pptx import Presentation  # noqa: E402

from app.main import app  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def test_full_flow():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ai_enabled"] is False

        # --- styles ---
        r = c.post("/api/styles", files={"file": ("biology_dark.pptx", (FIX / "biology_dark.pptx").read_bytes())}, data={"name": "Biology Dark"})
        assert r.status_code == 201, r.text
        style = r.json()
        kinds = style["profile"]["kinds"]
        assert kinds == {"title": 1, "content": 1, "image": 1, "section": 1}, kinds
        assert style["profile"]["background_tone"] == "dark"
        print("profile:", style["profile"]["fonts"], style["profile"]["palette"], style["profile"]["capacity"])

        r2 = c.post("/api/styles", files={"file": ("maths_layouts.pptx", (FIX / "maths_layouts.pptx").read_bytes())})
        assert r2.status_code == 201
        assert len(c.get("/api/styles").json()) == 2

        bad = c.post("/api/styles", files={"file": ("notes.txt", b"hello")})
        assert bad.status_code == 400
        bad2 = c.post("/api/styles", files={"file": ("fake.pptx", b"PK not really")})
        assert bad2.status_code == 400

        # --- image ---
        up = c.post("/api/images", files={"file": ("cell.png", (FIX / "sample_diagram.png").read_bytes())})
        assert up.status_code == 201, up.text
        image_id = up.json()["id"]

        # --- generate ---
        body = {
            "style_id": style["id"],
            "title": "Cells and Photosynthesis",
            "topic": "Year 9 biology",
            "slides": [
                {"page": 1, "details": "Cells and Photosynthesis. Year 9 Biology, Mr. Adams"},
                {"page": 2, "details": "What is a cell\nBasic unit of life\nAll living things are made of cells\nCells have a nucleus, membrane and cytoplasm"},
                {"page": 3, "details": "Label this diagram. Which part controls the cell?", "image_id": image_id},
                {"page": 4, "details": "Why do plants need chloroplasts? Plants make glucose using light energy. Chlorophyll absorbs light. Oxygen is released as a by-product. Glucose is stored as starch."},
            ],
        }
        g = c.post("/api/generate", json=body)
        assert g.status_code == 201, g.text
        gen = g.json()
        assert gen["mode"] == "mock" and len(gen["slides"]) == 4
        print("warnings:", gen["warnings"])

        dl = c.get(gen["download_url"])
        assert dl.status_code == 200
        out = Path(os.environ["STORAGE_DIR"]) / "result.pptx"
        out.write_bytes(dl.content)
        prs = Presentation(str(out))
        assert len(prs.slides) == 4, len(prs.slides)
        texts = ["\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame) for slide in prs.slides]
        print("\n=====\n".join(texts))
        assert "Welcome to Biology" not in "\n".join(texts), "sample text leaked"
        assert any(sh.shape_type == 13 for sh in prs.slides[2].shapes), "image slide has no picture"
        (Path(__file__).parent / "out" / "api_biology.pptx").write_bytes(dl.content)

        # same request on the layouts-based style
        body["style_id"] = r2.json()["id"]
        g2 = c.post("/api/generate", json=body)
        assert g2.status_code == 201, g2.text
        (Path(__file__).parent / "out" / "api_maths.pptx").write_bytes(c.get(g2.json()["download_url"]).content)
        print("maths warnings:", g2.json()["warnings"])

        # validation
        dup = dict(body); dup["slides"] = [{"page": 1, "details": "a"}, {"page": 1, "details": "b"}]
        assert c.post("/api/generate", json=dup).status_code == 400
        missing = dict(body); missing["style_id"] = "nope"
        assert c.post("/api/generate", json=missing).status_code == 404

        # delete style
        assert c.delete(f"/api/styles/{style['id']}").status_code == 204
        assert len(c.get("/api/styles").json()) == 1


def test_build_exact_content_without_ai(monkeypatch):
    """POST /api/build pours finished content into the style word for word, never calling the AI."""
    from app import ai

    def no_ai(*a, **k):
        raise AssertionError("the AI must not be called for exact builds")

    monkeypatch.setattr(ai, "generate_content", no_ai)
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        image_id = c.post("/api/images", files={"file": ("cell.png", (FIX / "sample_diagram.png").read_bytes())}).json()["id"]
        body = {
            "style_id": style["id"],
            "title": "Alcohol",
            "slides": [
                {"page": 2, "title": "Short-term effects", "bullets": ["Slower reaction times", "Poor judgement and risk-taking"],
                 "notes": "Ask: why is drink-driving dangerous?"},
                {"page": 1, "kind": "content", "role": "retrieval", "title": "Alcohol 5th Nov 2026",
                 "bullets": ["Retrieval Practice:", "What is a drug? (1)", "What is meant by addiction? (1)"]},
                {"page": 3, "title": "Look at the liver", "bullets": ["Where is it?"], "image_id": image_id},
            ],
        }
        r = c.post("/api/build", json=body)
        assert r.status_code == 201, r.text
        gen = r.json()
        assert gen["mode"] == "exact"
        assert [s["page"] for s in gen["slides"]] == [1, 2, 3]  # sorted by page
        assert gen["slides"][0]["bullets"] == ["Retrieval Practice:", "What is a drug? (1)", "What is meant by addiction? (1)"]

        deck = Presentation(io.BytesIO(c.get(gen["download_url"]).content))
        assert len(deck.slides) == 3
        text = " ".join(sh.text_frame.text for sh in deck.slides[1].shapes if sh.has_text_frame)
        assert "Slower reaction times" in text and "Poor judgement and risk-taking" in text
        assert deck.slides[1].notes_slide.notes_text_frame.text == "Ask: why is drink-driving dangerous?"
        assert any(sh.shape_type == 13 for sh in deck.slides[2].shapes)  # the attached picture

        dup = c.post("/api/build", json={**body, "slides": [body["slides"][0], {**body["slides"][1], "page": 2}]})
        assert dup.status_code == 400
        missing = c.post("/api/build", json={**body, "style_id": "nope"})
        assert missing.status_code == 404
