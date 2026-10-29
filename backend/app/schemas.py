from typing import Literal

from pydantic import BaseModel, Field

SlideKind = Literal["title", "content", "image", "section"]
# Where the teacher wants the attached picture: "auto" keeps the sample slide's own spot.
ImagePosition = Literal["auto", "left", "right", "top", "large", "none"]
HexColor = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}$")


class SlideSpec(BaseModel):
    """What the teacher typed for one page."""

    page: int = Field(ge=1, le=200)
    details: str = Field(default="", max_length=4000)
    image_id: str | None = None


class GenerateRequest(BaseModel):
    style_id: str
    title: str = Field(default="", max_length=200)
    # Cover slide: built from title + subtitle exactly as typed, ahead of the numbered slides.
    cover: bool = False
    subtitle: str = Field(default="", max_length=300)
    topic: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=2000)
    slides: list[SlideSpec] = Field(min_length=1, max_length=40)


class TextRun(BaseModel):
    """A stretch of text with the teacher's formatting. Unset fields keep the template's style."""

    text: str = Field(max_length=10000)
    bold: bool | None = None  # None: as the template has it
    italic: bool | None = None
    underline: bool | None = None
    size: float | None = Field(default=None, ge=6, le=120)  # points
    font: str | None = Field(default=None, max_length=64)
    color: str | None = HexColor
    highlight: str | None = HexColor


class SlideContent(BaseModel):
    """What the AI (or mock) produced for one page, plus the teacher's edits."""

    page: int
    kind: SlideKind = "content"
    title: str = ""
    subtitle: str = ""
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""
    # Set by the slide editor; when present they replace title / bullets (or subtitle).
    title_runs: list[TextRun] | None = Field(default=None, max_length=100)
    body_runs: list[list[TextRun]] | None = Field(default=None, max_length=30)
    image_position: ImagePosition = "auto"
    text_align: Literal["auto", "left", "center", "right"] = "auto"
    text_anchor: Literal["auto", "top", "middle", "bottom"] = "auto"


class BuildSlide(SlideContent):
    image_id: str | None = None


class BuildRequest(BaseModel):
    """Slides exactly as the teacher sees them in the editor; built without calling the AI."""

    style_id: str
    title: str = Field(default="", max_length=200)
    slides: list[BuildSlide] = Field(min_length=1, max_length=41)
