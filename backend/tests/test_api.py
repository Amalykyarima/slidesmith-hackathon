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


def test_cover_slide_comes_first_in_order():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("biology_dark.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        body = {
            "style_id": style["id"],
            "title": "Cells and Photosynthesis",
            "cover": True,
            "subtitle": "Year 9  |  Mr. Adams",
            "slides": [
                {"page": 1, "details": "What is a cell\nBasic unit of life\nAll living things are made of cells"},
                {"page": 2, "details": "Organelles\nNucleus controls the cell\nMitochondria release energy"},
                {"page": 3, "details": "Plenary\nWhat did we learn today\nOne thing you will remember"},
            ],
        }
        g = c.post("/api/generate", json=body)
        assert g.status_code == 201, g.text
        slides = g.json()["slides"]
        assert [s["page"] for s in slides] == [0, 1, 2, 3]
        assert slides[0] == {**slides[0], "kind": "title", "title": "Cells and Photosynthesis", "subtitle": "Year 9  |  Mr. Adams"}
        assert all(s["kind"] != "title" for s in slides[1:]), "only the cover is a title slide"

        prs = Presentation(str(Path(os.environ["STORAGE_DIR"]) / "outputs" / f"{g.json()['id']}.pptx"))
        texts = ["\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame) for slide in prs.slides]
        assert len(texts) == 4
        assert "Cells and Photosynthesis" in texts[0] and "Mr. Adams" in texts[0]
        assert [t.split("\n")[0] for t in texts[1:]] == ["What is a cell", "Organelles", "Plenary"]

        no_title = {**body, "title": "  "}
        assert c.post("/api/generate", json=no_title).status_code == 400


def test_draft_writes_text_without_building():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("biology_dark.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        before = len(c.get("/api/generations").json())
        r = c.post("/api/draft", json={
            "style_id": style["id"], "title": "Cells", "cover": True,
            "slides": [{"page": 1, "details": "Parts of a cell\nNucleus\nMembrane"}],
        })
        assert r.status_code == 200, r.text
        assert r.json()["slides"][0] == {**r.json()["slides"][0], "page": 1, "title": "Parts of a cell", "bullets": ["Nucleus", "Membrane"]}
        assert len(c.get("/api/generations").json()) == before, "a draft builds nothing"
        assert c.post("/api/draft", json={"style_id": "nope", "slides": [{"page": 1}]}).status_code == 404


def test_build_uses_the_teachers_slides_as_edited():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("biology_dark.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        image_id = c.post("/api/images", files={"file": ("cell.png", (FIX / "sample_diagram.png").read_bytes())}).json()["id"]
        slides = [
            {"page": 0, "kind": "title", "title": "Cells and Photosynthesis", "subtitle": "Year 9"},
            {"page": 1, "kind": "content", "title": "Parts of a cell",
             "title_runs": [{"text": "Parts of a "}, {"text": "cell", "bold": True, "color": "#00B050"}],
             "body_runs": [[{"text": "Nucleus"}], [{"text": "Membrane", "highlight": "#FFFF00"}]]},
            {"page": 2, "kind": "content", "title": "Label the diagram", "image_id": image_id, "image_position": "left"},
        ]
        r = c.post("/api/build", json={"style_id": style["id"], "slides": slides})
        assert r.status_code == 201, r.text
        gen = r.json()
        assert gen["mode"] == "manual" and gen["image_pages"] == [2]
        assert gen["title"] == "Cells and Photosynthesis", "the cover names the deck"

        prs = Presentation(str(Path(os.environ["STORAGE_DIR"]) / "outputs" / f"{gen['id']}.pptx"))
        texts = ["\n".join(s.text_frame.text for s in slide.shapes if s.has_text_frame) for slide in prs.slides]
        assert len(texts) == 3 and prs.core_properties.title == "Cells and Photosynthesis"
        assert "Year 9" in texts[0] and "Nucleus\n• Membrane" in texts[1], texts
        title_run = next(r for sh in prs.slides[1].shapes if sh.has_text_frame
                         for p in sh.text_frame.paragraphs for r in p.runs if r.text == "cell")
        assert title_run.font.bold and str(title_run.font.color.rgb) == "00B050"
        assert any(sh.shape_type == 13 for sh in prs.slides[2].shapes), "the picture is placed"

        dup = [slides[1], {**slides[1]}]
        assert c.post("/api/build", json={"style_id": style["id"], "slides": dup}).status_code == 400
        lost = [{**slides[2], "image_id": "gone"}]
        assert c.post("/api/build", json={"style_id": style["id"], "slides": lost}).status_code == 400
        assert c.post("/api/build", json={"style_id": "nope", "slides": slides}).status_code == 404


def test_blank_layouts_describe_where_text_goes():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("biology_dark.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        r = c.get(f"/api/styles/{style['id']}/layouts")
        assert r.status_code == 200, r.text
        data = r.json()
        assert [l["kind"] for l in data["layouts"]] == ["title", "content", "image", "section"]
        content = data["layouts"][1]
        assert content["title"] and content["body"] and content["body_look"]["size"] > 0
        assert all(0 <= v <= 1.01 for v in content["title"])
        assert content["body_room"] >= content["body"][3] and content["title_room"][1] >= content["title_room"][0]
        again = c.get(f"/api/styles/{style['id']}/layouts").json()
        assert again["layouts"][1]["title"] == content["title"], "cached"
        assert c.get("/api/styles/nope/layouts").status_code == 404


def test_cook_plans_a_whole_lesson_and_places_the_pictures():
    with TestClient(app) as c:
        style = c.post("/api/styles", files={"file": ("biology_dark.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        pics = [c.post("/api/images", files={"file": (f"p{n}.png", (FIX / "sample_diagram.png").read_bytes())}).json()["id"] for n in range(2)]
        r = c.post("/api/cook", json={
            "style_id": style["id"], "topic": "Photosynthesis",
            "description": "Year 9. Plants make glucose from light. Chlorophyll absorbs light. Oxygen is released.",
            "image_ids": pics,
        })
        assert r.status_code == 200, r.text
        deck = r.json()
        assert deck["mode"] == "mock" and deck["cover"]["title"] == "Photosynthesis"
        slides = deck["slides"]
        assert [s["page"] for s in slides] == list(range(1, len(slides) + 1))
        assert sorted(s["image_id"] for s in slides if s["image_id"]) == sorted(pics), "every picture used once"
        assert "Plants make glucose from light" in str(slides), "the description is used"

        sized = c.post("/api/cook", json={"style_id": style["id"], "topic": "Cells", "slide_count": 5}).json()
        assert len(sized["slides"]) == 5

        assert c.post("/api/cook", json={"style_id": style["id"], "topic": ""}).status_code == 422
        assert c.post("/api/cook", json={"style_id": style["id"], "topic": "x", "image_ids": ["gone"]}).status_code == 400
        assert c.post("/api/cook", json={"style_id": "nope", "topic": "x"}).status_code == 404
