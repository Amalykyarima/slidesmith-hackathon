import os
import tempfile
from types import SimpleNamespace


from app import ai, config  # noqa: E402
from app.schemas import GenerateRequest  # noqa: E402


def _written(page, kind, title, subtitle="", bullets=(), notes=""):
    return {"page": page, "kind": kind, "title": title, "subtitle": subtitle, "bullets": list(bullets), "notes": notes}


class FakeMessages:
    def parse(self, **kwargs):
        assert "tool_choice" not in kwargs, "forced tool use is rejected by current models"
        assert kwargs["fallbacks"] == "default" and kwargs["betas"] == ["server-side-fallback-2026-07-01"]
        assert kwargs["output_format"] is ai._WrittenSlides
        content = kwargs["messages"][0]["content"]
        assert any("Page 2" in b.get("text", "") for b in content if b["type"] == "text")
        parsed = ai._WrittenSlides.model_validate({"slides": [
            _written(1, "title", "Cells.", "Year 9"),
            # page 2 deliberately missing -> must fall back to teacher's notes
            _written(3, "content", "Organelles", bullets="abcdefghi"),
        ]})
        return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)


def test_claude_path(monkeypatch):
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages())))
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
        def parse(self, **kwargs):
            seen["text"] = "\n".join(b.get("text", "") for b in kwargs["messages"][0]["content"])
            return super().parse(**kwargs)

    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(beta=SimpleNamespace(messages=Messages())))
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


def test_cook_asks_for_a_whole_deck_and_places_pictures(monkeypatch, tmp_path):
    from PIL import Image

    from app.schemas import CookRequest

    pic = tmp_path / "p.png"
    Image.new("RGB", (40, 30), "red").save(pic)

    class Messages:
        def parse(self, **kwargs):
            assert kwargs["output_format"] is ai._CookedDeck and "tool_choice" not in kwargs
            text = " ".join(b.get("text", "") for b in kwargs["messages"][0]["content"])
            assert "Topic: Volcanoes" in text and "exactly 3" in text and "Picture 1:" in text
            deck = ai._CookedDeck.model_validate({
                "cover_title": "Volcanoes.", "cover_subtitle": "Year 8 Geography",
                "slides": [
                    {"kind": "content", "title": "Objectives", "subtitle": "", "bullets": ["a"], "notes": "", "picture": 0},
                    {"kind": "content", "title": "Eruption", "subtitle": "", "bullets": ["1", "2", "3", "4"], "notes": "", "picture": 1},
                    {"kind": "content", "title": "Again", "subtitle": "", "bullets": [], "notes": "", "picture": 1},
                ],
            })
            return SimpleNamespace(stop_reason="end_turn", parsed_output=deck)

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(beta=SimpleNamespace(messages=Messages())))
    req = CookRequest(style_id="x", topic="Volcanoes", slide_count=3)
    cover, slides, mode = ai.cook(req, [("img1", pic)], {"max_bullets": 5, "max_words_per_bullet": 12})
    assert mode == "ai" and cover.title == "Volcanoes"
    assert [s.image_id for s in slides] == [None, "img1", None], "a picture is used once"
    assert len(slides[1].bullets) == 3, "picture slides keep the text short"

    class Refusing:
        def parse(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)

    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(beta=SimpleNamespace(messages=Refusing())))
    try:
        ai.cook(req, [], {"max_bullets": 5, "max_words_per_bullet": 12})
        raise AssertionError("a refusal must surface")
    except ai.AIError as exc:
        assert "declined" in str(exc)
