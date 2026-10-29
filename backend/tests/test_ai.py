import os
import tempfile
from types import SimpleNamespace


from app import ai, config  # noqa: E402
from app.schemas import GenerateRequest  # noqa: E402


class FakeMessages:
    def create(self, **kwargs):
        assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_slides"}
        content = kwargs["messages"][0]["content"]
        assert any("Page 2" in b.get("text", "") for b in content if b["type"] == "text")
        block = SimpleNamespace(
            type="tool_use",
            input={
                "slides": [
                    {"page": 1, "kind": "title", "title": "Cells.", "subtitle": "Year 9"},
                    # page 2 deliberately missing -> must fall back to teacher's notes
                    {"page": 3, "kind": "content", "title": "Organelles", "bullets": ["a", "b", "c", "d", "e", "f", "g", "h", "i"]},
                    {"page": 9, "kind": "bogus", "title": "malformed"},
                ]
            },
        )
        return SimpleNamespace(content=[block])


def test_claude_path(monkeypatch):
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=FakeMessages()))
    req = GenerateRequest(
        style_id="x",
        title="Cells",
        slides=[
            {"page": 1, "details": "intro"},
            {"page": 2, "details": "Mitochondria\nPower house of the cell"},
            {"page": 3, "details": "organelles"},
        ],
    )
    slides, mode = ai.generate_content(req, {}, {"max_bullets": 5, "max_words_per_bullet": 12})
    assert mode == "ai"
    assert [s.page for s in slides] == [1, 2, 3]
    assert slides[0].title == "Cells"  # trailing full stop stripped
    assert slides[1].title == "Mitochondria"  # fallback from teacher's notes
    assert len(slides[2].bullets) == 5  # capped to the style's capacity


def test_cover_means_no_other_title_slide(monkeypatch):
    """With a separate cover, the model's 'title' kind is downgraded and the prompt says so."""
    monkeypatch.setattr(config, "AI_ENABLED", True)
    seen = {}

    class Messages(FakeMessages):
        def create(self, **kwargs):
            seen["text"] = "\n".join(b.get("text", "") for b in kwargs["messages"][0]["content"])
            return super().create(**kwargs)

    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=Messages()))
    req = GenerateRequest(
        style_id="x", title="Cells", cover=True,
        slides=[{"page": 1, "details": "intro"}, {"page": 2, "details": "x"}, {"page": 3, "details": "y"}],
    )
    slides, _ = ai.generate_content(req, {}, {"max_bullets": 5, "max_words_per_bullet": 12})
    assert "cover slide is made separately" in seen["text"]
    assert [s.kind for s in slides][0] == "section"  # model said "title" for page 1

    monkeypatch.setattr(config, "AI_ENABLED", False)
    mock, mode = ai.generate_content(req, {}, {"max_bullets": 5, "max_words_per_bullet": 12})
    assert mode == "mock" and all(s.kind != "title" for s in mock)
