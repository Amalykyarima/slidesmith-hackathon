from typing import Literal

from pydantic import BaseModel, Field

SlideKind = Literal["title", "content", "image", "section"]


class SlideSpec(BaseModel):
    """What the teacher typed for one page."""

    page: int = Field(ge=1, le=200)
    details: str = Field(default="", max_length=4000)
    image_id: str | None = None


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
    # Which of the style's sample slides (0-based) this page is built from. Set by the
    # builder; when a teacher picks a layout in the editor, it forces that sample.
    sample: int | None = None
    # Picture shown on this page (uploaded via /api/images), kept so the deck can be rebuilt.
    image_id: str | None = None


class BuildSlide(SlideContent):
    """A finished slide the teacher (or an imported lesson file) already wrote."""

    page: int = Field(ge=1, le=200)
    title: str = Field(default="", max_length=300)
    subtitle: str = Field(default="", max_length=500)
    bullets: list[str] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=2000)
    image_id: str | None = None


class RebuildRequest(BaseModel):
    """The edited slides of a generated deck, in their new order."""

    title: str | None = Field(default=None, max_length=200)
    slides: list[BuildSlide] = Field(min_length=1, max_length=40)


class BuildRequest(BaseModel):
    """Build a deck from finished content, word for word, without the AI."""

    style_id: str
    title: str = Field(default="", max_length=200)
    slides: list[BuildSlide] = Field(min_length=1, max_length=40)
