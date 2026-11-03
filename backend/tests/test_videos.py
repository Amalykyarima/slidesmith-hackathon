"""Video links: a clickable thumbnail with a play button, and clickable web addresses."""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from app import videos
from app.main import app

FIX = Path(__file__).parent / "fixtures"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No network in tests; thumbnails go to a fresh folder."""
    monkeypatch.setattr(videos, "THUMBS_DIR", tmp_path / "thumbs")

    def no_network(url, limit=0):
        raise OSError("offline")

    monkeypatch.setattr(videos, "_fetch", no_network)


def _jpg(size, color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://youtube.com/live/dQw4w9WgXcQ",
])
def test_youtube_ids(url):
    assert videos.youtube_id(url) == "dQw4w9WgXcQ"


def test_not_youtube():
    assert videos.youtube_id("https://vimeo.com/76979871") is None
    assert videos.youtube_id("https://www.youtube.com/@somechannel") is None


def test_clean_url():
    assert videos.clean_url("  youtu.be/dQw4w9WgXcQ ") == "https://youtu.be/dQw4w9WgXcQ"
    for bad in ["hello world", "ftp://x.com/a", "javascript:alert(1)", "https://"]:
        with pytest.raises(ValueError):
            videos.clean_url(bad)


def test_youtube_thumbnail_has_red_play_button(monkeypatch):
    monkeypatch.setattr(videos, "_fetch", lambda url, limit=0: _jpg((480, 360), (40, 120, 200)))
    path = videos.thumbnail(YT)
    with Image.open(path) as im:
        assert im.size == videos.SIZE  # cropped to 16:9
        r, g, b = im.getpixel((im.width // 2 - 100, im.height // 2))  # on the button, left of the triangle
        assert r > 180 and g < 90 and b < 90
        assert im.getpixel((40, 40))[2] > 150  # the video frame around it
    assert videos.is_thumbnail(path)
    assert videos.thumbnail(YT) == path  # cached


def test_offline_or_other_sites_get_a_card():
    path = videos.thumbnail("https://vimeo.com/76979871")
    with Image.open(path) as im:
        assert im.size == videos.SIZE
        assert max(im.getpixel((20, 20))) < 80  # dark card


def test_web_addresses_become_links():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(2))
    box.text_frame.text = "Revise at https://www.bbc.co.uk/bitesize/guides/abc. Then try (https://example.org/q)"
    assert videos.link_urls(slide) == 2
    runs = box.text_frame.paragraphs[0].runs
    assert [(r.text, r.hyperlink.address) for r in runs] == [
        ("Revise at ", None),
        ("https://www.bbc.co.uk/bitesize/guides/abc", "https://www.bbc.co.uk/bitesize/guides/abc"),
        (". Then try (", None),
        ("https://example.org/q", "https://example.org/q"),
        (")", None),
    ]
    assert videos.link_urls(slide) == 0  # already linked: left alone


def _build(c, slides):
    style = c.post("/api/styles", files={"file": ("bio.pptx", (FIX / "biology_dark.pptx").read_bytes())}).json()
    r = c.post("/api/build", json={"style_id": style["id"], "slides": slides})
    return r


def test_build_with_video_links():
    with TestClient(app) as c:
        image_id = c.post("/api/images", files={"file": ("c.png", (FIX / "sample_diagram.png").read_bytes())}).json()["id"]
        r = _build(c, [
            {"page": 1, "title": "Watch this", "bullets": ["What do you notice?"], "video_url": YT},
            {"page": 2, "title": "Both", "bullets": ["Look at the diagram."], "image_id": image_id,
             "video_url": "vimeo.com/76979871"},
            {"page": 3, "title": "Reading", "bullets": ["Read https://www.bbc.co.uk/bitesize tonight"]},
        ])
        assert r.status_code == 201, r.text
        deck = Presentation(io.BytesIO(c.get(r.json()["download_url"]).content))
        one, two, three = deck.slides

        pics = [s for s in one.shapes if s.shape_type == 13 and s.click_action.hyperlink.address]
        assert [p.click_action.hyperlink.address for p in pics] == [YT]
        assert YT in one.notes_slide.notes_text_frame.text
        assert "youtube.com" not in " ".join(s.text_frame.text for s in one.shapes if s.has_text_frame)

        watch = [r for s in two.shapes if s.has_text_frame for p in s.text_frame.paragraphs for r in p.runs
                 if videos.WATCH_LINE in r.text]
        assert watch and watch[0].hyperlink.address == "https://vimeo.com/76979871"
        assert not [s for s in two.shapes if s.shape_type == 13 and s.click_action.hyperlink.address]

        links = [r.hyperlink.address for s in three.shapes if s.has_text_frame
                 for p in s.text_frame.paragraphs for r in p.runs if r.hyperlink.address]
        assert links == ["https://www.bbc.co.uk/bitesize"]


def test_bad_video_link_is_explained():
    with TestClient(app) as c:
        r = _build(c, [{"page": 1, "title": "x", "video_url": "not a link"}])
        assert r.status_code == 400 and "Page 1" in r.json()["detail"]
