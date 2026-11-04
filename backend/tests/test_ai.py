import os
import tempfile
from types import SimpleNamespace


from app import ai, config  # noqa: E402
from app.schemas import GenerateRequest  # noqa: E402


class FakeMessages:
    def create(self, **kwargs):
        assert kwargs["tool_choice"] == {"type": "auto"}  # newer models reject forced tool use
        assert kwargs["tools"][0]["strict"] is True
        content = kwargs["messages"][0]["content"]
        assert any("Page 2" in b.get("text", "") for b in content if b["type"] == "text")
        block = SimpleNamespace(
            type="tool_use", name="submit_slides",
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
    # 9 bullets from the model: not cut to the style's estimate (5), only to the hard cap of 8.
    assert len(slides[2].bullets) == 8


def test_routine_roles_reach_the_prompt_and_come_back(monkeypatch):
    seen = {}

    class RoleMessages:
        def create(self, **kwargs):
            seen["text"] = "\n".join(b.get("text", "") for b in kwargs["messages"][0]["content"])
            seen["system"] = kwargs["system"]
            block = SimpleNamespace(type="tool_use", name="submit_slides", input={"slides": [
                {"page": 1, "kind": "content", "title": "Alcohol 5th Nov 2026", "role": "retrieval",
                 "bullets": ["Retrieval Practice:", "What is a drug? (1)"]},
                {"page": 2, "kind": "content", "title": "Short-term effects", "role": "not-a-role"},
            ]})
            return SimpleNamespace(content=[block])

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=RoleMessages()))
    req = GenerateRequest(style_id="x", slides=[{"page": 1, "details": "retrieval"}, {"page": 2, "details": "effects"}])
    capacity = {"max_bullets": 6, "max_words_per_bullet": 14,
                "roles": {"retrieval": {"title": "Nutrients 24th Sep 2026", "label": "Retrieval Practice:"},
                          "exit": {"title": "Lesson Exit Routines", "label": ""}}}
    slides, _ = ai.generate_content(req, {}, capacity)

    assert '- retrieval: "Nutrients 24th Sep 2026" [label: "Retrieval Practice:"]' in seen["text"]
    assert "Lesson Exit Routines" not in seen["text"]  # never offered as a page type
    assert "word for word" in seen["system"]
    assert slides[0].role == "retrieval" and slides[1].role == ""


def test_asks_again_when_the_model_answers_in_text(monkeypatch):
    """With tool_choice auto the model may reply in prose: one reminder, then the slides."""
    calls = []

    class Chatty:
        def create(self, **kwargs):
            calls.append(kwargs["messages"])
            if len(calls) == 1:
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="Here are your slides...")],
                                       stop_reason="end_turn")
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="submit_slides", input={
                "slides": [{"page": 1, "kind": "content", "title": "Cells", "subtitle": "", "bullets": ["x"],
                            "notes": "", "role": ""}]})], stop_reason="tool_use")

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai.anthropic, "Anthropic", lambda **kw: SimpleNamespace(messages=Chatty()))
    req = GenerateRequest(style_id="x", slides=[{"page": 1, "details": "cells"}])
    slides, mode = ai.generate_content(req, {}, {"max_bullets": 6, "max_words_per_bullet": 12})
    assert mode == "ai" and slides[0].title == "Cells"
    assert len(calls) == 2 and calls[1][-1]["content"] == ai.NUDGE  # append-only: answer, then reminder
    assert calls[1][-2]["role"] == "assistant"
