"""Video links on slides: a clickable thumbnail with a play button.

A teacher pastes a YouTube (or any) video link for a page. The slide gets a picture of the
video with a play button; clicking it in PowerPoint, Google Slides or Keynote opens the
video. Web addresses typed in the text become clickable links too.
"""
from __future__ import annotations

import copy
import hashlib
import io
import logging
import re
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pptx.oxml.ns import qn
from pptx.text.text import _Run

from . import config

log = logging.getLogger("slidesmith.videos")

THUMBS_DIR = config.IMAGES_DIR / "video-thumbnails"
WATCH_LINE = "▶ Watch the video"
SIZE = (1280, 720)
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# A web address in typed text (stops at spaces and closing brackets/quotes).
URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+")


def clean_url(url: str) -> str:
    """The link as typed, checked: must be http(s) with a host. Raises ValueError."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    parts = urlparse(url)
    host = parts.hostname or ""
    if (parts.scheme not in ("http", "https") or not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host)
            or " " in url or len(url) > 500):
        raise ValueError("That doesn't look like a web link. Copy it from the browser's address bar.")
    return url


def youtube_id(url: str) -> str | None:
    """The 11-character video id from youtube.com/watch, youtu.be, shorts, embed or live links."""
    parts = urlparse(url)
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.").removeprefix("music.")
    candidate = None
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if parts.path == "/watch":
            candidate = (parse_qs(parts.query).get("v") or [None])[0]
        else:
            bits = parts.path.strip("/").split("/")
            if len(bits) >= 2 and bits[0] in ("shorts", "embed", "live", "v"):
                candidate = bits[1]
    return candidate if candidate and _YT_ID.match(candidate) else None


def _fetch(url: str, limit: int = 3_000_000) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SlideSmith/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:  # noqa: S310 (fixed https host)
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("thumbnail too large")
    return data


def _youtube_frame(video_id: str) -> Image.Image | None:
    """YouTube's own thumbnail (hqdefault is 4:3 with black bars: crop to 16:9)."""
    for name in ("maxresdefault", "hqdefault"):
        try:
            im = Image.open(io.BytesIO(_fetch(f"https://img.youtube.com/vi/{video_id}/{name}.jpg"))).convert("RGB")
        except Exception:  # noqa: BLE001 (offline, missing size, blocked): try the next / fall back
            continue
        if im.width < 200:  # YouTube's grey "no thumbnail" placeholder is 120x90
            continue
        return ImageOps.fit(im, SIZE, Image.LANCZOS)
    return None


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "Carlito-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _card(url: str) -> Image.Image:
    """No picture of the video: a plain dark card naming the site."""
    im = Image.new("RGB", SIZE, (33, 37, 41))
    draw = ImageDraw.Draw(im)
    for y in range(SIZE[1]):  # gentle vertical gradient
        shade = int(33 + 22 * y / SIZE[1])
        draw.line([(0, y), (SIZE[0], y)], fill=(shade, shade + 4, shade + 10))
    host = urlparse(url).netloc.lower().removeprefix("www.")
    label = "YouTube video" if youtube_id(url) else (f"Video · {host}" if host else "Video")
    font = _font(46)
    w = draw.textlength(label, font=font)
    draw.text(((SIZE[0] - w) / 2, SIZE[1] * 0.74), label, font=font, fill=(235, 238, 242))
    return im


def _play_button(im: Image.Image, youtube: bool) -> Image.Image:
    """Draw a play button in the middle (YouTube red for YouTube, dark for anything else)."""
    scale = 4  # draw big, shrink: smooth edges
    w, h = 300, 210
    layer = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fill = (230, 33, 23, 235) if youtube else (84, 92, 106, 255)
    d.rounded_rectangle([0, 0, w * scale - 1, h * scale - 1], radius=60 * scale, fill=fill)
    cx, cy, r = w * scale / 2 + 10 * scale, h * scale / 2, 62 * scale
    d.polygon([(cx - r * 0.8, cy - r), (cx - r * 0.8, cy + r), (cx + r, cy)], fill=(255, 255, 255, 255))
    layer = layer.resize((w, h), Image.LANCZOS)
    out = im.convert("RGBA")
    out.alpha_composite(layer, ((out.width - w) // 2, (out.height - h) // 2 - (40 if not youtube else 0)))
    return out.convert("RGB")


def thumbnail(url: str) -> Path:
    """A 16:9 picture for the video with a play button, cached on disk per link."""
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    path = THUMBS_DIR / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.jpg"
    if path.exists():
        return path
    vid = youtube_id(url)
    frame = _youtube_frame(vid) if vid else None
    if vid and frame is None:
        log.info("No YouTube thumbnail for %s; using a plain card", vid)
    im = _play_button(frame if frame is not None else _card(url), youtube=frame is not None)
    im.save(path, "JPEG", quality=88)
    return path


def is_thumbnail(path: Path | None) -> bool:
    return path is not None and Path(path).parent == THUMBS_DIR


# --------------------------------------------------------------------------- #
# Making things clickable in the finished deck
# --------------------------------------------------------------------------- #
def link_picture(slide, picture_path: Path, url: str) -> bool:
    """Make the picture that came from `picture_path` open `url` when clicked."""
    want = hashlib.sha1(Path(picture_path).read_bytes()).hexdigest()
    for shape in slide.shapes:
        if shape.shape_type == 13 and shape.image.sha1 == want:
            shape.click_action.hyperlink.address = url
            shape._element.nvPicPr.cNvPr.set("descr", f"Video: {url}"[:250])
            return True
    return False


def link_text(slide, text: str, url: str) -> bool:
    """Give the run(s) reading exactly `text` a link to `url`."""
    found = False
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for p in shape.text_frame.paragraphs:
            if p.text.strip().endswith(text):
                for r in p.runs:
                    r.hyperlink.address = url
                found = True
    return found


def link_urls(slide) -> int:
    """Turn web addresses typed in a slide's text into clickable links. Returns how many."""
    count = 0
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for p in shape.text_frame.paragraphs:
            for r in list(p.runs):
                text = r.text
                if "http" not in text or r.hyperlink.address:
                    continue
                pieces, last = [], 0
                for m in URL_IN_TEXT.finditer(text):
                    url = m.group(0).rstrip(".,;:!?")
                    end = m.start() + len(url)
                    pieces += [(text[last:m.start()], None), (url, url)]
                    last = end
                if not any(link for _, link in pieces):
                    continue
                pieces.append((text[last:], None))
                pieces = [(t, link) for t, link in pieces if t]
                el = r._r
                for t, link in pieces:
                    new = copy.deepcopy(el)
                    new.find(qn("a:t")).text = t
                    el.addprevious(new)
                    if link:
                        _Run(new, p).hyperlink.address = link
                        count += 1
                el.getparent().remove(el)
    return count
