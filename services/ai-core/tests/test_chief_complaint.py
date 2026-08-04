"""Unit tests for the ticket's chief complaint (Feature 23).

All OpenAI access is mocked — no live API calls (see `tests/conftest.py`).
Covers the deterministic fallback, the two rules that keep the field
trustworthy (an intake answer is not a complaint; a worse value never
replaces a better one), and the best-effort contract every caller relies on.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tickets.chief_complaint import (
    MAX_CHARS,
    available,
    condense,
    derive,
    derive_from_history,
    refresh,
)


def _run(coro):
    return asyncio.run(coro)


def _fake_client(content: str) -> SimpleNamespace:
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=completion))))


# --- availability gating ---------------------------------------------------

def test_available_follows_the_api_key():
    with patch("app.tickets.chief_complaint.settings") as settings:
        settings.openai_api_key = ""
        assert available() is False
        settings.openai_api_key = "sk-test"
        assert available() is True


# --- condense: the deterministic fallback ---------------------------------

def test_condense_takes_the_citizens_opening_sentence():
    assert condense("No power in Anna Nagar since Tuesday. Please help urgently.") \
        == "No power in Anna Nagar since Tuesday"


def test_condense_pulls_in_the_next_sentence_when_the_first_is_a_fragment():
    # "No power" alone is a useless queue column; the following sentence is
    # where the location actually is.
    assert condense("No power. Whole street is dark in Anna Nagar.") \
        == "No power. Whole street is dark in Anna Nagar"


def test_condense_collapses_newlines_and_runs_of_whitespace():
    # An email body arrives with hard wraps; the chief complaint is one line.
    assert condense("  Water   supply\n\n   cut for three days  ") == "Water supply cut for three days"


def test_condense_drops_the_intake_details_block_we_appended_ourselves():
    # `service._format_message_content` appends this — it is our formatting,
    # not the citizen's complaint, so it must never reach the chief complaint.
    text = ("Streetlight not working on 2nd Street\n\n---\nCitizen-provided details:\n"
            "Service/Customer ID: 56784567\nMobile: 9876543210")
    assert condense(text) == "Streetlight not working on 2nd Street"


def test_condense_truncates_on_a_word_boundary_never_mid_word():
    long_text = "Sewage overflowing " + "in the back lane behind the market " * 10
    result = condense(long_text)
    assert len(result) <= MAX_CHARS + 1  # +1 for the ellipsis
    assert result.endswith("…")
    assert not result[:-1].endswith(" ")
    # The cut fell between words, so every word in the result is whole.
    assert long_text.startswith(result[:-1])


def test_condense_of_nothing_is_nothing():
    assert condense(None) is None
    assert condense("") is None
    assert condense("   \n  ") is None


# --- derive: an intake answer is not a complaint --------------------------

def test_derive_ignores_an_intake_form_answer():
    # Feature 20's live bug in a new place: intake answers are usually a
    # WhatsApp stub's 2nd/3rd/4th messages, so without this guard the chief
    # complaint of most tickets would end up being the citizen's own phone
    # number or email address.
    for answer in ["Nithya", "nithya@gmail.com", "56784567", "Name: Nithya"]:
        assert _run(derive("No power in Anna Nagar", answer)) is None, answer


def test_derive_ignores_an_intake_answer_even_when_there_is_nothing_to_keep():
    assert _run(derive(None, "9876543210")) is None


def test_derive_of_a_blank_message_changes_nothing():
    assert _run(derive("No power", "")) is None
    assert _run(derive("No power", None)) is None


# --- derive: the LLM path -------------------------------------------------

def test_derive_uses_the_models_line_when_it_revises():
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client(
            '{"chief_complaint": "No power in Anna Nagar 2nd Street since Tuesday", "changed": true}')

        result = _run(derive("No power in Anna Nagar", "It is the whole of 2nd Street, since Tuesday"))

    assert result == "No power in Anna Nagar 2nd Street since Tuesday"


def test_derive_keeps_the_existing_line_when_the_model_says_nothing_changed():
    # The common case: "any update?" adds nothing about the problem. Asked of
    # the model explicitly rather than diffed, so a reworded-but-equivalent
    # line doesn't count as a change either.
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client(
            '{"chief_complaint": "No power in Anna Nagar", "changed": false}')

        assert _run(derive("No power in Anna Nagar", "Any update on this please?")) is None


def test_derive_reports_no_change_when_the_model_returns_the_same_line():
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client(
            '{"chief_complaint": "No power in Anna Nagar", "changed": true}')

        assert _run(derive("No power in Anna Nagar", "Still no power")) is None


def test_derive_caps_an_overlong_model_answer():
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client(
            '{"chief_complaint": "' + "x" * 500 + '", "changed": true}')

        assert len(_run(derive(None, "Sewage overflowing"))) == MAX_CHARS


def test_derive_falls_back_to_the_citizens_own_words_when_the_llm_fails():
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI", side_effect=RuntimeError("boom")):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"

        assert _run(derive(None, "No water supply since Monday. Please fix.")) \
            == "No water supply since Monday"


def test_derive_never_downgrades_an_existing_line_to_a_raw_truncation():
    # The rule that keeps the field trustworthy: an LLM outage leaves a
    # previously-derived line alone rather than overwriting it with the raw
    # first sentence of whatever the citizen just typed.
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI", side_effect=RuntimeError("boom")):
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"

        assert _run(derive("No power in Anna Nagar since Tuesday", "It happens around 11PM")) is None


def test_derive_falls_back_when_the_model_returns_unparseable_json():
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client_cls.return_value = _fake_client("not json at all")

        assert _run(derive(None, "Meter reading is wrong")) == "Meter reading is wrong"


def test_derive_without_a_key_uses_the_deterministic_path_and_calls_no_client():
    with patch("app.tickets.chief_complaint.AsyncOpenAI") as client_cls:
        result = _run(derive(None, "Garbage not collected for a week"))

    assert result == "Garbage not collected for a week"
    client_cls.assert_not_called()


# --- derive_from_history: one call over a whole conversation --------------

def test_derive_from_history_puts_every_citizen_message_to_the_model_at_once():
    with patch("app.tickets.chief_complaint.settings") as settings, \
            patch("app.tickets.chief_complaint.AsyncOpenAI") as client_cls:
        settings.openai_api_key = "sk-test"
        settings.openai_model = "gpt-4o-mini"
        client = _fake_client(
            '{"chief_complaint": "No power on 2nd Street since Tuesday", "changed": true}')
        client_cls.return_value = client

        result = _run(derive_from_history(
            ["No power", "Nithya", "It is the whole of 2nd Street", "Since Tuesday"]))

    assert result == "No power on 2nd Street since Tuesday"
    # ONE request for the whole conversation, not one per message.
    client.chat.completions.create.assert_awaited_once()
    prompt = client.chat.completions.create.await_args.kwargs["messages"][1]["content"]
    assert "1. No power" in prompt
    assert "2nd Street" in prompt
    # The intake answer is dropped before the model sees it — it is an answer to
    # our question, not a description of a problem.
    assert "Nithya" not in prompt


def test_derive_from_history_falls_back_to_the_first_real_message():
    # No key: the citizen's own opening sentence still beats a blank cell.
    assert _run(derive_from_history(["9876543210", "No water since Monday. Please help."])) \
        == "No water since Monday"


def test_derive_from_history_of_nothing_usable_is_none():
    assert _run(derive_from_history([])) is None
    assert _run(derive_from_history(["", "   "])) is None
    # Every message was intake data — there is no complaint here to describe.
    assert _run(derive_from_history(["Nithya", "56784567"])) is None


# --- refresh: read, derive, write only on a change -----------------------

def test_refresh_writes_the_derived_line_onto_the_ticket():
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"id": "t-1", "chief_complaint": None})
    db.get_messages = AsyncMock(return_value=[
        {"direction": "inbound", "content": "No power in Anna Nagar since Tuesday"},
    ])

    result = _run(refresh(db, "t-1", "No power in Anna Nagar since Tuesday", trace_id="tr-1"))

    assert result == "No power in Anna Nagar since Tuesday"
    db.update_ticket.assert_awaited_once()
    ticket_id, payload = db.update_ticket.await_args.args
    assert ticket_id == "t-1"
    assert payload == {"chiefComplaint": "No power in Anna Nagar since Tuesday"}


def test_refresh_derives_a_first_value_from_the_whole_history_not_just_this_message():
    """Found while backfilling: a ticket with no chief complaint yet may already
    have a conversation — every pre-V12 row is in that state. Deriving from the
    latest message alone would record "any update?" as the complaint."""
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"chief_complaint": None})
    db.get_messages = AsyncMock(return_value=[
        {"direction": "inbound", "content": "No power in Anna Nagar since Tuesday"},
        {"direction": "outbound", "content": "We are looking into it"},
        {"direction": "inbound", "content": "Any update?"},
    ])

    result = _run(refresh(db, "t-1", "Any update?"))

    # The real complaint wins over the follow-up that triggered this refresh.
    assert result == "No power in Anna Nagar since Tuesday"
    # Outbound messages are never part of the citizen's complaint.
    assert "looking into it" not in (result or "")


def test_refresh_includes_this_message_when_it_is_not_yet_persisted():
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"chief_complaint": None})
    db.get_messages = AsyncMock(return_value=[])

    assert _run(refresh(db, "t-1", "Sewage overflowing on Lattice Bridge Road")) \
        == "Sewage overflowing on Lattice Bridge Road"


def test_refresh_still_derives_when_the_history_fetch_fails():
    # Best-effort: a message-history failure degrades to "just this message"
    # rather than leaving the ticket with no chief complaint at all.
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"chief_complaint": None})
    db.get_messages = AsyncMock(side_effect=RuntimeError("db down"))

    assert _run(refresh(db, "t-1", "Transformer sparking near the school")) \
        == "Transformer sparking near the school"


def test_refresh_with_an_existing_line_does_not_reread_the_history():
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"chief_complaint": "No power in Anna Nagar"})

    # Without a key the deterministic path can only ever restate the message,
    # and an existing line is never downgraded — so there is nothing to write.
    assert _run(refresh(db, "t-1", "Any update?")) is None
    db.update_ticket.assert_not_called()
    # The incremental path costs no extra fetch — that is once per ticket only.
    db.get_messages.assert_not_called()


def test_refresh_writes_nothing_for_an_intake_answer():
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"chief_complaint": "No power in Anna Nagar"})

    assert _run(refresh(db, "t-1", "56784567")) is None
    db.update_ticket.assert_not_called()


def test_refresh_swallows_a_db_failure_rather_than_breaking_the_turn():
    # Every caller is on the path of a reply the citizen is waiting for, so a
    # chief-complaint problem must never surface as an exception.
    db = AsyncMock()
    db.get_ticket = AsyncMock(side_effect=RuntimeError("db down"))

    assert _run(refresh(db, "t-1", "No power")) is None


def test_refresh_swallows_a_failed_write():
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"chief_complaint": None})
    db.update_ticket = AsyncMock(side_effect=RuntimeError("db down"))

    assert _run(refresh(db, "t-1", "No power in Anna Nagar")) is None
