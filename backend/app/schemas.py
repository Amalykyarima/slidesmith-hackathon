import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SlideKind = Literal["title", "content", "image", "section"]


class SlideSpec(BaseModel):
    """What the teacher typed for one page."""

    page: int = Field(ge=1, le=200)
    details: str = Field(default="", max_length=4000)
    image_id: str | None = None
    video_url: str | None = Field(default=None, max_length=500)  # shown as a clickable thumbnail
    # Which of her template's slides to copy (1-based slide number). None = SlideSmith chooses.
    sample: int | None = Field(default=None, ge=1, le=500)


class GenerateRequest(BaseModel):
    style_id: str
    title: str = Field(default="", max_length=200)
    topic: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=2000)
    slides: list[SlideSpec] = Field(default_factory=list, max_length=40)
    # Replaces the dates on the teacher's sample slides. Default: the next school day.
    lesson_date: dt.date | None = None
    # Whole-lesson mode (no slides listed): the AI plans `slide_count` slides from this brief.
    brief: str = Field(default="", max_length=4000)
    slide_count: int | None = Field(default=None, ge=2, le=30)
    # Her "LO:" and "Keywords:" strips. Empty = the AI writes them.
    lo: str = Field(default="", max_length=300)
    keywords: str = Field(default="", max_length=300)
    # Who the lesson is for: "primary", "secondary" or "university" (see levels.py).
    level: str = Field(default="secondary", max_length=20)
    # Add SEN scaffolding (simpler wording, symbols, step cards). None = the orchestrator decides.
    sen: bool | None = None

    @model_validator(mode="after")
    def _slides_or_brief(self):
        if not self.slides and not (self.slide_count and self.brief.strip()):
            raise ValueError("Add notes for at least one slide, or give a topic and a number of slides.")
        return self

    @property
    def whole_lesson(self) -> bool:
        return not self.slides


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
    # Her template slide to copy (1-based). None = the best match.
    sample: int | None = Field(default=None, ge=1, le=500)


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
    lesson_date: dt.date | None = None
    lo: str = Field(default="", max_length=300)
    keywords: str = Field(default="", max_length=300)
