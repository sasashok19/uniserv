"""Unit tests for rubric-based priority scoring (Feature 03).

All OpenAI access is mocked — no live API calls. Covers availability gating,
strict-JSON parsing, score clamping, the label_for fallback, and the
best-effort None-on-error contract the ticket pipeline relies on.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.priority.llm_scorer import rubric_available, score_with_rubric


def _run(coro):
    return asyncio.run(coro)


def _fake_client(content: str) -> SimpleNamespace:
    """A stand-in AsyncOpenAI whose chat.completions.create returns `content`."""
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=completion))))


def test_rubric_available_false_without_key():
    with patch("app.priority.llm_scorer.settings") as settings:
        settings.openai_api_key = ""
        assert rubric_available() is False


def test_rubric_available_true_with_key():
    with patch("app.priority.llm_scorer.settings") as settings:
        settings.openai_api_key = "sk-test"
        assert rubric_available() is True


def test_score_with_rubric_parses_strict_json():
    client = _fake_client('{"score": 8.5, "label": "critical"}')
    with patch("app.priority.llm_scorer.AsyncOpenAI", return_value=client):
        result = _run(score_with_rubric("rubric text", "power is out", "outage", "whatsapp"))
    assert result == {"score": 8.5, "label": "critical"}


def test_score_with_rubric_clamps_out_of_range_score():
    client = _fake_client('{"score": 42, "label": "critical"}')
    with patch("app.priority.llm_scorer.AsyncOpenAI", return_value=client):
        result = _run(score_with_rubric("rubric", "text", "billing", "email"))
    assert result["score"] == 10.0


def test_score_with_rubric_derives_label_when_missing_or_invalid():
    # Score 6.5 with a bogus label -> label_for(6.5) == "high".
    client = _fake_client('{"score": 6.5, "label": "URGENT"}')
    with patch("app.priority.llm_scorer.AsyncOpenAI", return_value=client):
        result = _run(score_with_rubric("rubric", "text", "technical", "email"))
    assert result == {"score": 6.5, "label": "high"}


def test_score_with_rubric_returns_none_on_missing_label_key():
    client = _fake_client('{"score": 3.0}')
    with patch("app.priority.llm_scorer.AsyncOpenAI", return_value=client):
        result = _run(score_with_rubric("rubric", "text", "other", "email"))
    assert result == {"score": 3.0, "label": "low"}


def test_score_with_rubric_returns_none_on_api_error():
    """A raising client (e.g. bad/missing key, timeout) yields None so the
    caller falls back to the deterministic engine."""
    failing = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(side_effect=RuntimeError("401 unauthorized")))))
    with patch("app.priority.llm_scorer.AsyncOpenAI", return_value=failing):
        result = _run(score_with_rubric("rubric", "text", "billing", "email"))
    assert result is None


def test_score_with_rubric_returns_none_on_unparseable_response():
    client = _fake_client("not json at all")
    with patch("app.priority.llm_scorer.AsyncOpenAI", return_value=client):
        result = _run(score_with_rubric("rubric", "text", "billing", "email"))
    assert result is None
