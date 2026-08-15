"""Ask before creating a duplicate (Feature 26) — the confirmation module.

The routing-level behaviour lives in ``test_routing_ladder.py``; this covers the
pieces underneath it: what counts as a plain yes/no, how a substantive answer is
re-judged, and what the question the citizen sees actually says.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.conversation import menu_content
from app.dedup import confirmation


def _run(coro):
    return asyncio.run(coro)


TENANT = "t1"
THREAD = "whatsapp:+919876543210"

_DUPLICATE_OF = {
    "id": "t-1",
    "ticketNumber": "TKT-00042",
    "category": "power",
    "summary": "Power cut in Madambakkam since yesterday evening",
}


def _pending(text="Power cut"):
    return {"text": text, "question": "Which area is the power cut in?",
            "duplicateOf": dict(_DUPLICATE_OF)}


def _db():
    db = MagicMock()
    db.add_message = AsyncMock(return_value={"id": "m-1"})
    db.add_event = AsyncMock(return_value={"id": "e-1"})
    return db


# --- plain yes/no ----------------------------------------------------------

def test_plain_affirmatives_are_recognised_without_an_llm():
    for text in ("yes", "Yes", "yeah", "yep", "correct", "same", "it is",
                 "Yes it is", "same issue", "aama", "y"):
        assert confirmation.classify_answer(text) is True, text


def test_plain_negatives_are_recognised_without_an_llm():
    for text in ("no", "No", "nope", "nah", "different", "not the same",
                 "another one", "illai", "n"):
        assert confirmation.classify_answer(text) is False, text


def test_a_substantive_answer_is_left_for_the_model():
    """"Madambakkam" and "no, this one is in Velachery" both carry information
    a first-word match would throw away."""
    for text in ("Madambakkam", "no, this one is in Velachery", "near the temple",
                 "yes but also the street light is out", "", None):
        assert confirmation.classify_answer(text) is None, text


# --- resolution ------------------------------------------------------------

def test_a_yes_resolves_to_the_existing_ticket_without_calling_the_model(fake_valkey):
    rejudge = AsyncMock()
    with patch("app.dedup.confirmation.match_open_ticket", rejudge):
        outcome = _run(confirmation.resolve(_db(), TENANT, THREAD, _pending(), "yes"))

    assert outcome == {"outcome": "same", "ticketId": "t-1", "ticketNumber": "TKT-00042"}
    rejudge.assert_not_awaited()


def test_a_no_resolves_to_a_new_complaint_carrying_the_original_words(fake_valkey):
    with patch("app.dedup.confirmation.match_open_ticket", AsyncMock()):
        outcome = _run(confirmation.resolve(_db(), TENANT, THREAD, _pending(), "no"))

    assert outcome["outcome"] == "different"
    assert "Power cut" in outcome["text"]


def test_a_substantive_answer_is_rejudged_with_the_whole_complaint(fake_valkey):
    """Re-judging the answer alone would compare "Madambakkam" to a power-cut
    complaint and conclude, correctly but uselessly, that they differ."""
    rejudge = AsyncMock(return_value={"index": 0, "verdict": "same", "reason": "same place",
                                      "question": None})
    with patch("app.dedup.confirmation.match_open_ticket", rejudge):
        outcome = _run(confirmation.resolve(_db(), TENANT, THREAD, _pending(), "Madambakkam"))

    assert outcome["outcome"] == "same"
    judged_text = rejudge.await_args.args[1]
    assert "Power cut" in judged_text and "Madambakkam" in judged_text


def test_a_different_locality_becomes_its_own_complaint(fake_valkey):
    rejudge = AsyncMock(return_value={"index": None, "verdict": "different",
                                      "reason": "different locality", "question": None})
    with patch("app.dedup.confirmation.match_open_ticket", rejudge):
        outcome = _run(confirmation.resolve(_db(), TENANT, THREAD, _pending(), "Velachery"))

    assert outcome["outcome"] == "different"
    assert "Power cut" in outcome["text"] and "Velachery" in outcome["text"]


def test_a_still_ambiguous_answer_ends_the_round_rather_than_asking_again(fake_valkey):
    rejudge = AsyncMock(return_value={"index": 0, "verdict": "unclear", "reason": "still vague",
                                      "question": "Which area?"})
    with patch("app.dedup.confirmation.match_open_ticket", rejudge):
        outcome = _run(confirmation.resolve(_db(), TENANT, THREAD, _pending(), "over there"))

    assert outcome["outcome"] == "unclear"
    assert outcome["duplicateOf"]["ticketNumber"] == "TKT-00042"


def test_an_unavailable_model_creates_and_flags_rather_than_dropping_the_complaint(fake_valkey):
    """A network condition is not a decision. An agent settling a flagged pair
    is recoverable; a complaint dropped because OpenAI was down is not."""
    with patch("app.dedup.confirmation.match_open_ticket", AsyncMock(return_value=None)):
        outcome = _run(confirmation.resolve(_db(), TENANT, THREAD, _pending(), "somewhere"))

    assert outcome["outcome"] == "unclear"


# --- attaching -------------------------------------------------------------

def test_attaching_writes_the_message_and_audits_the_prevented_duplicate(fake_valkey):
    db = _db()

    assert _run(confirmation.attach_to_existing(
        db, TENANT, "t-1", "whatsapp", "Power cut\nMadambakkam")) is True

    _, payload = db.add_message.await_args.args
    assert payload["content"] == "Power cut\nMadambakkam"
    assert payload["direction"] == "inbound" and payload["authorType"] == "user"
    assert db.add_event.await_args.args[1]["eventType"] == "ticket.duplicate_prevented"


def test_a_failed_attach_is_reported_so_the_caller_does_not_acknowledge_it(fake_valkey):
    db = _db()
    db.add_message = AsyncMock(side_effect=RuntimeError("db down"))

    assert _run(confirmation.attach_to_existing(db, TENANT, "t-1", "whatsapp", "x")) is False


def test_a_failed_audit_write_does_not_lose_the_message(fake_valkey):
    db = _db()
    db.add_event = AsyncMock(side_effect=RuntimeError("db down"))

    assert _run(confirmation.attach_to_existing(db, TENANT, "t-1", "whatsapp", "x")) is True


def test_attaching_nothing_is_refused(fake_valkey):
    assert _run(confirmation.attach_to_existing(_db(), TENANT, "t-1", "whatsapp", "   ")) is False
    assert _run(confirmation.attach_to_existing(_db(), TENANT, None, "whatsapp", "x")) is False


# --- the question the citizen sees -----------------------------------------

def test_the_question_names_the_complaint_we_already_hold():
    """A citizen cannot answer a question about a record they cannot see."""
    content = menu_content.resolve({})

    text = confirmation.build_question(content, _DUPLICATE_OF, "Which area is the power cut in?")

    assert "TKT-00042" in text
    assert "Madambakkam" in text
    assert "Which area is the power cut in?" in text


def test_the_question_works_without_tenant_menu_copy():
    """Email has no configurable menu and must still get a sensible question."""
    text = confirmation.build_question(None, _DUPLICATE_OF, "Which area?")

    assert "TKT-00042" in text and "Madambakkam" in text and "Which area?" in text


def test_a_long_existing_complaint_is_truncated_in_the_question():
    long_one = dict(_DUPLICATE_OF, summary="x" * 400)

    text = confirmation.build_question(None, long_one, "Which area?")

    assert "..." in text and len(text) < 400


def test_the_question_survives_an_unnumbered_ticket():
    text = confirmation.build_question(None, {"summary": "Power cut"}, "Which area?")
    assert "Which area?" in text


# --- state -----------------------------------------------------------------

def test_pending_state_round_trips_and_clears(fake_valkey):
    _run(confirmation.save_pending(TENANT, THREAD, _pending()))

    assert _run(confirmation.load_pending(TENANT, THREAD))["duplicateOf"]["id"] == "t-1"
    assert fake_valkey.ttls[f"dupconfirm:{TENANT}:{THREAD}"] == \
        confirmation.PENDING_TTL_HOURS * 3600

    _run(confirmation.clear_pending(TENANT, THREAD))
    assert _run(confirmation.load_pending(TENANT, THREAD)) is None


def test_the_pending_window_never_outlives_the_reply_window_it_lives_in():
    # A question a citizen can no longer be answered about is worse than none.
    assert confirmation.PENDING_TTL_HOURS <= menu_content.MAX_SESSION_TTL_HOURS


def test_unreadable_pending_state_reads_as_none(fake_valkey):
    fake_valkey.store[f"dupconfirm:{TENANT}:{THREAD}"] = "{not json"
    assert _run(confirmation.load_pending(TENANT, THREAD)) is None


def test_as_pending_captures_what_the_answer_will_need():
    pending = confirmation.as_pending(
        "Power cut", {"id": "t-1", "ticket_number": "TKT-00042", "category": "power"},
        "Power cut in Madambakkam", "Which area?")

    assert pending["text"] == "Power cut"
    assert pending["duplicateOf"] == {"id": "t-1", "ticketNumber": "TKT-00042",
                                      "category": "power",
                                      "summary": "Power cut in Madambakkam"}
    assert json.loads(json.dumps(pending)) == pending, "must survive a Valkey round trip"
