from typing import Literal

from pydantic import BaseModel, Field

SlideKind = Literal["title", "content", "image", "section"]


class SlideSpec(BaseModel):
    """What the teacher typed for one page."""

    page: int = Field(ge=1, le=200)
    details: str = Field(default="", max_length=4000)
    image_id: str | None = None
    video_url: str | None = Field(default=None, max_length=500)  # shown as a clickable thumbnail


class GenerateRequest(BaseModel):
    style_id: str
    title: str = Field(default="", max_length=200)
    topic: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=2000)
    slides: list[SlideSpec] = Field(min_length=1, max_length=40)


class SlideContent(BaseModel):
    """What the AI (or mock) produced for one page."""

    page: int
    kind: SlideKind = "content"
    title: str = ""
    subtitle: str = ""
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""
    # Routine slide this page should copy (see roles.py), e.g. "retrieval". Empty = ordinary slide.
    role: str = ""


class BuildSlide(SlideContent):
    """A finished slide the teacher (or an imported lesson file) already wrote."""

    page: int = Field(ge=1, le=200)
    title: str = Field(default="", max_length=300)
    subtitle: str = Field(default="", max_length=500)
    bullets: list[str] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=2000)
    image_id: str | None = None
    video_url: str | None = Field(default=None, max_length=500)


class TextRun(BaseModel):
    text: str = Field(default="", max_length=5000)
    size: float | None = None
    color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None


class EditParagraph(BaseModel):
    runs: list[TextRun] = Field(default_factory=list, max_length=200)


class ShapeEdit(BaseModel):
    """One text box or picture the teacher moved, resized or re-formatted (EMU, points)."""

    id: int
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    paragraphs: list[EditParagraph] | None = Field(default=None, max_length=200)


class SlideEdits(BaseModel):
    shapes: list[ShapeEdit] = Field(default_factory=list, max_length=200)


class BuildRequest(BaseModel):
    """Build a deck from finished content, word for word, without the AI."""

    style_id: str
    title: str = Field(default="", max_length=200)
    slides: list[BuildSlide] = Field(min_length=1, max_length=40)
