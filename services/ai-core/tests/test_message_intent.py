"""Unit tests for the inbound intent judgment and quoted-text stripping (Feature 24).

All OpenAI access is mocked. The contract that matters: on ANY failure
`assess_inbound` returns None, and the caller must then ask the citizen rather
than guess a ticket — the opposite bias to most judgments in this codebase, and
deliberately so, because guessing is what misrouted the reported message.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.classify.message_intent import assess_inbound, available
from app.classify.text_cleanup import strip_quoted_reply


def _run(coro):
    return asyncio.run(coro)


def _fake_client(content: str) -> SimpleNamespace:
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=completion))))


_QUESTIONS = [
    {"ticketNumber": "TKT-00010", "status": "resolved",
     "question": "Is this resolved?", "complaint": "No power in Anna Nagar"},
    {"ticketNumber": "TKT-00014", "status": "open",
     "question": "What is your meter number?", "complaint": "Wrong bill"},
]


def _with_model(content):
    settings = patch("app.classify.message_intent.settings")
    client = patch("app.classify.message_intent.AsyncOpenAI")
    return settings, client, content


# --- availability ----------------------------------------------------------

def test_available_follows_the_api_key():
    with patch("app.classify.message_intent.settings") as settings:
        settings.openai_api_key = ""
        assert available() is False
        settings.openai_api_key = "sk-test"
        assert available() is True


def test_without_a_key_the_judgment_is_unavailable_not_a_guess():
    # conftest blanks the key, so no patching needed. None means "ask", never
    # "assume it's a new complaint" or "assume it answers ticket 1".
    assert _run(assess_inbound(_QUESTIONS, "Yes it is")) is None


# --- the three-way answer --------------------------------------------------

def test_a_confirmation_is_matched_to_the_question_it_fits():
    with patch("app.classify.message_intent.settings") as settings, \
            patch("app.classify.message_intent.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client(
            '{"answers_ticket": 1, "is_new_complaint": false, "reason": "answers is-this-resolved"}')

        result = _run(assess_inbound(_QUESTIONS, "Yes it is"))

    assert result == {"index": 0, "is_new_complaint": False, "reason": "answers is-this-resolved"}


def test_a_message_can_both_answer_us_and_raise_a_new_problem():
    with patch("app.classify.message_intent.settings") as settings, \
            patch("app.classify.message_intent.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client(
            '{"answers_ticket": 2, "is_new_complaint": true, "reason": "gives the meter and reports a leak"}')

        result = _run(assess_inbound(_QUESTIONS, "84402215, and there is a leak on my street"))

    assert result["index"] == 1
    assert result["is_new_complaint"] is True


def test_a_hallucinated_ticket_number_means_none_never_an_arbitrary_ticket():
    """The failure that would recreate the bug: a model naming position 7 of a
    2-item list must not be read as "some ticket"."""
    for bad in ("7", "0", "-1", "true", "null", '"TKT-00010"'):
        with patch("app.classify.message_intent.settings") as settings, \
                patch("app.classify.message_intent.AsyncOpenAI") as client_cls:
            settings.openai_api_key = "sk-test"
            settings.openai_model = "gpt-4o-mini"
            client_cls.return_value = _fake_client(
                '{"answers_ticket": ' + bad + ', "is_new_complaint": false, "reason": "x"}')

            result = _run(assess_inbound(_QUESTIONS, "Yes"))

        assert result["index"] is None, bad


def test_an_empty_question_list_still_answers_the_new_complaint_question():
    """First contact: nothing outstanding, so the only question left is whether
    this is a complaint at all."""
    with patch("app.classify.message_intent.settings") as settings, \
            patch("app.classify.message_intent.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client(
            '{"answers_ticket": null, "is_new_complaint": true, "reason": "describes an outage"}')

        result = _run(assess_inbound([], "No power in my area"))

    assert result == {"index": None, "is_new_complaint": True, "reason": "describes an outage"}
    prompt = client_cls.return_value.chat.completions.create.await_args.kwargs["messages"][1]["content"]
    assert "we are not waiting on anything" in prompt


def test_the_prompt_carries_the_question_the_complaint_and_the_status():
    with patch("app.classify.message_intent.settings") as settings, \
            patch("app.classify.message_intent.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client('{"answers_ticket": 1, "is_new_complaint": false}')

        _run(assess_inbound(_QUESTIONS, "Yes it is"))

    prompt = client_cls.return_value.chat.completions.create.await_args.kwargs["messages"][1]["content"]
    assert "Is this resolved?" in prompt
    assert "No power in Anna Nagar" in prompt
    # The status is shown because a resolved ticket must NOT be disqualified —
    # that exclusion is what caused the reported misroute.
    assert "resolved" in prompt


def test_any_failure_returns_none_so_the_caller_asks():
    for side_effect in (RuntimeError("boom"),):
        with patch("app.classify.message_intent.settings") as settings, \
                patch("app.classify.message_intent.AsyncOpenAI", side_effect=side_effect):
            settings.openai_api_key = "sk-test"
            settings.openai_model = "gpt-4o-mini"
            assert _run(assess_inbound(_QUESTIONS, "Yes")) is None


def test_unparseable_json_returns_none_rather_than_a_default_guess():
    with patch("app.classify.message_intent.settings") as settings, \
            patch("app.classify.message_intent.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client("not json")

        assert _run(assess_inbound(_QUESTIONS, "Yes")) is None


# --- quoted-text stripping ------------------------------------------------

def test_strips_a_gmail_style_quote():
    raw = ("Yes it is\n\n"
           "On Mon, 4 Aug 2026 at 09:12, UniServe <x@y.com> wrote:\n"
           "> Is this resolved?\n> Your complaint about water logging")
    assert strip_quoted_reply(raw) == "Yes it is"


def test_strips_an_outlook_style_quote():
    raw = "No it is not\n\n-----Original Message-----\nFrom: UniServe\nIs this resolved?"
    assert strip_quoted_reply(raw) == "No it is not"


def test_strips_a_bare_quoted_block():
    assert strip_quoted_reply("ok\n> please confirm") == "ok"


def test_strips_our_own_notification_boilerplate_quoted_back():
    """Our status-update mail invites a reply, so it comes back quoted. Leaving
    it in would let "Ticket ID: TKT-00010" be read as the citizen's own
    reference and route by rung 1 on our words, not theirs."""
    raw = ("It is still not fixed\n\n"
           "Your complaint has been updated.\nTicket ID: TKT-00010\nStatus: resolved")
    assert strip_quoted_reply(raw) == "It is still not fixed"


def test_strips_a_phone_signature():
    assert strip_quoted_reply("Yes fixed now\n\nSent from my iPhone") == "Yes fixed now"
    assert strip_quoted_reply("Thanks\n--\nRavi Kumar") == "Thanks"


def test_a_message_that_is_entirely_quoted_material_is_returned_unchanged():
    """Better to judge the raw text than to hand the caller an empty string it
    would read as "no message"."""
    raw = "> Is this resolved?"
    assert strip_quoted_reply(raw) == raw


def test_plain_text_is_untouched():
    assert strip_quoted_reply("No power in Anna Nagar since Tuesday") \
        == "No power in Anna Nagar since Tuesday"
    assert strip_quoted_reply("") == ""
    assert strip_quoted_reply(None) == ""


def test_a_complaint_mentioning_the_word_wrote_is_not_truncated():
    """The quote markers are anchored to a line start and require the trailing
    colon, so ordinary prose survives."""
    text = "I wrote to you last week about the meter and nobody replied"
    assert strip_quoted_reply(text) == text
