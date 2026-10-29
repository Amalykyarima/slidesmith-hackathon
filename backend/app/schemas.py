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
