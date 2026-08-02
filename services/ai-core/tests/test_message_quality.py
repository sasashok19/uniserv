"""Unit tests for message quality assessment (Feature 18).

All OpenAI access is mocked — no live API calls. Covers availability
gating, strict-JSON parsing, and the best-effort None-on-error contract
every caller relies on to "fail open" (never silently drop a real
complaint because the LLM hiccupped).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.classify.message_quality import assess_coherence, available, is_same_topic


def _run(coro):
    return asyncio.run(coro)


def _fake_client(content: str) -> SimpleNamespace:
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=completion))))


def test_available_false_without_key():
    with patch("app.classify.message_quality.settings") as settings:
        settings.openai_api_key = ""
        assert available() is False


def test_available_true_with_key():
    with patch("app.classify.message_quality.settings") as settings:
        settings.openai_api_key = "sk-test"
        assert available() is True


# --- assess_coherence ------------------------------------------------------

def test_assess_coherence_empty_message_is_incoherent_without_any_llm_call():
    with patch("app.classify.message_quality.AsyncOpenAI") as client_cls:
        result = _run(assess_coherence("   "))
    assert result == {"coherent": False, "reason": "empty message"}
    client_cls.assert_not_called()


def test_assess_coherence_returns_none_when_unavailable():
    with patch("app.classify.message_quality.settings") as settings:
        settings.openai_api_key = ""
        result = _run(assess_coherence("some text"))
    assert result is None


def test_assess_coherence_parses_coherent_true():
    client = _fake_client('{"coherent": true, "reason": null}')
    with patch("app.classify.message_quality.settings") as settings, \
         patch("app.classify.message_quality.AsyncOpenAI", return_value=client):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        result = _run(assess_coherence("no power"))
    assert result == {"coherent": True, "reason": None}


def test_assess_coherence_parses_coherent_false_with_reason():
    client = _fake_client('{"coherent": false, "reason": "looks like random characters"}')
    with patch("app.classify.message_quality.settings") as settings, \
         patch("app.classify.message_quality.AsyncOpenAI", return_value=client):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        result = _run(assess_coherence("asdkfj qwoeiu"))
    assert result == {"coherent": False, "reason": "looks like random characters"}


def test_assess_coherence_returns_none_on_api_error():
    failing = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(side_effect=RuntimeError("timeout")))))
    with patch("app.classify.message_quality.settings") as settings, \
         patch("app.classify.message_quality.AsyncOpenAI", return_value=failing):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        result = _run(assess_coherence("some text"))
    assert result is None


def test_assess_coherence_returns_none_on_unparseable_response():
    client = _fake_client("not json at all")
    with patch("app.classify.message_quality.settings") as settings, \
         patch("app.classify.message_quality.AsyncOpenAI", return_value=client):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        result = _run(assess_coherence("some text"))
    assert result is None


# --- is_same_topic -----------------------------------------------------------

def test_is_same_topic_returns_none_when_unavailable():
    with patch("app.classify.message_quality.settings") as settings:
        settings.openai_api_key = ""
        result = _run(is_same_topic("No power in my area", "outage", "Put not closed"))
    assert result is None


def test_is_same_topic_parses_false_for_unrelated_complaint():
    """The exact reported scenario: 'No power' vs 'Put not closed'."""
    client = _fake_client('{"same_topic": false, "reason": "different subject matter"}')
    with patch("app.classify.message_quality.settings") as settings, \
         patch("app.classify.message_quality.AsyncOpenAI", return_value=client):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        result = _run(is_same_topic("No power in my area", "outage", "Put not closed"))
    assert result is False


def test_is_same_topic_parses_true_for_a_genuine_followup():
    client = _fake_client('{"same_topic": true, "reason": "vague follow-up"}')
    with patch("app.classify.message_quality.settings") as settings, \
         patch("app.classify.message_quality.AsyncOpenAI", return_value=client):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        result = _run(is_same_topic("No power in my area", "outage", "any update on this?"))
    assert result is True


def test_is_same_topic_returns_none_on_api_error():
    failing = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(side_effect=RuntimeError("401 unauthorized")))))
    with patch("app.classify.message_quality.settings") as settings, \
         patch("app.classify.message_quality.AsyncOpenAI", return_value=failing):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        result = _run(is_same_topic("existing", "other", "new"))
    assert result is None
