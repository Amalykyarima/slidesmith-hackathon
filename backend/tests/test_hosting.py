"""Hosted mode: access-code sign-in, each teacher sees only her own work, a daily AI
cap, previews limited to the first slides, and the Angular app served by FastAPI."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation

from app import ai, auth, config
from app.main import app
from app.previews import _first_slides
from app.schemas import SlideContent

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(config, "ACCESS_CODES", {"maple-42": "Mrs Khan", "river-7": "Mr Lee"})
    monkeypatch.setattr(config, "AUTH_ENABLED", True)


def _signed_in(code: str) -> TestClient:
    c = TestClient(app)
    c.__enter__()
    r = c.post("/api/login", json={"code": code})
    assert r.status_code == 200, r.text
    return c


def test_parse_codes():
    assert config._parse_codes("Mrs Khan:maple-42, Mr Lee:river-7,") == {"maple-42": "Mrs Khan", "river-7": "Mr Lee"}
    assert config._parse_codes("solo-code") == {"solo-code": "Teacher"}
    assert config._parse_codes("") == {}


def test_tokens_cannot_be_forged_or_reused_after_expiry():
    good = auth.make_token("Mrs Khan")
    assert auth.read_token(good) == "Mrs Khan"
    payload, sig = good.rsplit(".", 1)
    assert auth.read_token(payload + "." + "0" * len(sig)) is None
    assert auth.read_token(auth.make_token("Mrs Khan", now=time.time() - auth.MAX_AGE - 5)) is None
    assert auth.read_token("garbage") is None and auth.read_token(None) is None
    # Every name gives a cookie-safe token (no "=" padding that would get the cookie quoted).
    for name in ["Mr Lee", "Mrs Khan", "A", "Ms O'Brien-Smith"]:
        token = auth.make_token(name)
        assert "=" not in token and auth.read_token(token) == name
        assert auth.read_token(f'"{token}"') == name


def test_sign_in_is_required(hosted):
    with TestClient(app) as c:
        assert c.get("/api/health").json()["auth_required"] is True
        assert c.get("/api/session").json() == {"auth_required": True, "name": None}
        assert c.get("/api/styles").status_code == 401
        assert c.get("/files/images/anything.png").status_code == 401
        assert c.post("/api/login", json={"code": "wrong"}).status_code == 401
        r = c.post("/api/login", json={"code": " maple-42 "})
        assert r.json() == {"name": "Mrs Khan"}
        assert "httponly" in r.headers["set-cookie"].lower()
        assert c.get("/api/session").json()["name"] == "Mrs Khan"
        assert c.get("/api/styles").status_code == 200
        c.post("/api/logout")
        assert c.get("/api/styles").status_code == 401


def test_teachers_only_see_their_own_work(hosted):
    khan, lee = _signed_in("maple-42"), _signed_in("river-7")
    try:
        style = khan.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        image = khan.post("/api/images", files={"file": ("c.png", (FIX / "sample_diagram.png").read_bytes())}).json()
        gen = khan.post("/api/build", json={"style_id": style["id"], "title": "Mine",
                                            "slides": [{"page": 1, "title": "Hello", "bullets": ["One"]}]}).json()
        assert [s["id"] for s in khan.get("/api/styles").json()] == [style["id"]]

        assert lee.get("/api/styles").json() == []
        assert lee.get(f"/api/styles/{style['id']}").status_code == 404
        assert lee.delete(f"/api/styles/{style['id']}").status_code == 404
        assert lee.get(f"/api/generations/{gen['id']}").status_code == 404
        assert lee.get(f"/api/generations/{gen['id']}/download").status_code == 404
        assert lee.get("/api/generations").json() == []
        assert lee.post("/api/build", json={"style_id": style["id"], "slides": [{"page": 1, "title": "x"}]}).status_code == 404
        lee_style = lee.post("/api/styles", files={"file": ("m.pptx", (FIX / "maths_layouts.pptx").read_bytes())}).json()
        r = lee.post("/api/build", json={"style_id": lee_style["id"],
                                         "slides": [{"page": 1, "title": "x", "image_id": image["id"]}]})
        assert r.status_code == 400  # Mrs Khan's picture isn't Mr Lee's to use
        assert khan.get(f"/api/generations/{gen['id']}/download").status_code == 200
    finally:
        khan.__exit__(None, None, None)
        lee.__exit__(None, None, None)


def test_daily_ai_limit(hosted, monkeypatch):
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(config, "AI_DAILY_LIMIT", 1)
    monkeypatch.setattr(ai, "generate_content",
                        lambda req, images, cap, extras=None: ([SlideContent(page=1, title="AI slide", bullets=["x"])], "ai"))
    c = _signed_in("maple-42")
    try:
        style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
        body = {"style_id": style["id"], "slides": [{"page": 1, "details": "notes"}]}
        assert c.post("/api/generate", json=body).status_code == 201
        second = c.post("/api/generate", json=body)
        assert second.status_code == 429 and "no AI" in second.json()["detail"]
        exact = c.post("/api/build", json={"style_id": style["id"], "slides": [{"page": 1, "title": "still fine"}]})
        assert exact.status_code == 201  # exact builds don't count
    finally:
        c.__exit__(None, None, None)


def test_previews_only_first_slides(tmp_path):
    prs = Presentation()
    for _ in range(5):
        prs.slides.add_slide(prs.slide_layouts[6])
    deck = tmp_path / "five.pptx"
    prs.save(deck)
    assert _first_slides(deck, tmp_path, 0) == deck
    assert _first_slides(deck, tmp_path, 9) == deck
    work = tmp_path / "work"
    work.mkdir()
    trimmed = _first_slides(deck, work, 2)
    assert trimmed != deck and len(Presentation(str(trimmed)).slides) == 2
    assert len(Presentation(str(deck)).slides) == 5  # the original is untouched


def test_serves_the_angular_app(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<app-root></app-root>")
    (tmp_path / "main-abc.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    monkeypatch.setattr(config, "FRONTEND_DIST", tmp_path)
    with TestClient(app) as c:
        assert "app-root" in c.get("/").text
        assert "app-root" in c.get("/create").text  # client-side route
        assert c.get("/main-abc.js").text == "console.log(1)"
        assert "app-root" in c.get("/..%2Fsecret.txt").text  # no escaping the build folder
        assert c.get("/api/does-not-exist").status_code == 404
        assert c.get("/api/health").json()["ok"] is True


def test_thumbnails_are_made_in_a_separate_process(tmp_path):
    """PyMuPDF stays out of the server: it runs in `python -m app.raster`."""
    import subprocess
    import sys

    import pymupdf

    pdf = tmp_path / "two.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=720, height=405)
    doc.save(pdf)
    out = tmp_path / "thumbs"
    out.mkdir()
    done = subprocess.run([sys.executable, "-m", "app.raster", str(pdf), str(out), "320", "2"],
                          capture_output=True, text=True, cwd=str(config.BASE_DIR), check=True)
    assert done.stdout.strip() == "2"
    assert sorted(p.name for p in out.glob("*.jpg")) == ["1.jpg", "2.jpg"]

    code = "import sys, app.main; print('pymupdf' in sys.modules)"
    loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(config.BASE_DIR))
    assert loaded.stdout.strip() == "False"
