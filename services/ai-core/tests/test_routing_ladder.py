"""The inbound routing ladder (Feature 24).

The bug these exist for, in the reporter's words: "I opened a complaint
TKT-00010 which is in resolved status and sent a message 'Is this resolved?'. I
replied 'Yes it is'. Now in the portal I see this message is updated against the
ticket TKT-00014, this is completely wrong."

Three compounding causes, each covered below:
1. `resolved` (and `pending_customer`) were excluded from the routing candidate
   set, so TKT-00010 could not be found at all.
2. "Yes it is" is structurally an intake-form answer, so the intake guard
   claimed it for whichever stub happened to be mid-intake.
3. The id of the message the citizen replied TO was never stored, so the one
   exact signal available was unusable.

All OpenAI access is mocked (see `tests/conftest.py`), so these assert routing
decisions, not model behaviour.
"""

import asyncio
from unittest.mock import AsyncMock, patch

from app.dedup.service import ADDRESSABLE_STATUSES, OPEN_STATUSES
from app.tickets.intake import ASK_FOR_REFERENCE, ensure_ticket_stub


def _run(coro):
    return asyncio.run(coro)


def _msg(direction, content, created_at="2999-01-01 00:00:00", **extra):
    """A ticket_messages row. `created_at` defaults far in the future so it is
    inside the reply window unless a test deliberately makes it stale."""
    return {"direction": direction, "content": content, "created_at": created_at, **extra}


def _db(tickets=None, messages=None, identity="m-1", ask_count=0):
    """A db-writer mock with SAFE defaults for every collaborator the ladder
    touches.

    Defaults matter here: an unconfigured `AsyncMock` returns a truthy mock, so
    a test that forgot `find_message_by_channel_id` would silently resolve at
    rung 0 and pass for the wrong reason.

    `messages` maps ticket id -> its message timeline.
    """
    db = AsyncMock()
    db.find_message_by_channel_id = AsyncMock(return_value=None)
    db.get_tenant_config = AsyncMock(return_value={})
    db.unrouted_ask_count = AsyncMock(return_value=ask_count)
    db.create_unrouted_message = AsyncMock(return_value={"id": "u-1"})
    db.add_event = AsyncMock(return_value={})
    db.find_by_phone = AsyncMock(return_value={"master_id": identity} if identity else None)
    db.find_by_email = AsyncMock(return_value={"master_id": identity} if identity else None)
    db.create_ticket = AsyncMock(return_value={"id": "new-1", "ticketNumber": "TKT-99999"})
    db.get_messages = AsyncMock(side_effect=lambda tid, **kw: (messages or {}).get(tid, []))
    db.get_ticket = AsyncMock(side_effect=lambda tid, **kw: next(
        (t for t in (tickets or []) if t["id"] == tid), {}))

    def list_tickets(_tenant, **filters):
        if filters.get("ticketNumber"):
            return [t for t in (tickets or []) if t.get("ticket_number") == filters["ticketNumber"]]
        if filters.get("originMessageId"):
            return [t for t in (tickets or []) if t.get("origin_message_id") == filters["originMessageId"]]
        return list(tickets or [])

    db.list_tickets = AsyncMock(side_effect=list_tickets)
    return db


def _intent(index=None, is_new_complaint=False, reason="stub"):
    return {"index": index, "is_new_complaint": is_new_complaint, "reason": reason}


def _ticket(tid, number, status="open", **extra):
    return {"id": tid, "ticket_number": number, "status": status, **extra}


# --- The reported bug ------------------------------------------------------

def test_a_yes_reply_reaches_the_resolved_ticket_we_asked_on_not_another_one():
    """The exact reported case. TKT-00010 is RESOLVED and is the ticket we asked
    "Is this resolved?" on; TKT-00014 is an unrelated open stub that used to
    swallow the reply."""
    resolved = _ticket("t-10", "TKT-00010", status="resolved")
    other_stub = _ticket("t-14", "TKT-00014", status="open")
    db = _db(
        tickets=[resolved, other_stub],
        messages={
            "t-10": [_msg("inbound", "No power in Anna Nagar"),
                     _msg("outbound", "Is this resolved?")],
            "t-14": [_msg("outbound", "Please share your name", is_intake_request=1)],
        },
    )

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(index=0, reason="answers 'Is this resolved?'"))):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+919000000000", "whatsapp", raw_text="Yes it is",
            channel_identity_type="phone", channel_identity_value="+919000000000",
            trace_id="tr-bug"))

    assert stub == {"id": "t-10", "ticketNumber": "TKT-00010"}
    db.create_ticket.assert_not_called()


def test_a_resolved_ticket_is_in_the_candidate_set_at_all():
    """Cause 1 on its own: routing must ASK about terminal-status tickets. The
    old `OPEN_STATUSES` filter meant a resolved ticket was never a candidate, so
    no judgment could have saved it."""
    db = _db(tickets=[_ticket("t-10", "TKT-00010", status="resolved")],
             messages={"t-10": [_msg("outbound", "Is this resolved?")]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())) as assess:
        _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes it is",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-1"))

    assert db.list_tickets.await_args_list[0].kwargs["status"] == ADDRESSABLE_STATUSES
    # ...and the resolved ticket's outstanding question was actually offered.
    questions = assess.await_args.args[0]
    assert [q["ticketNumber"] for q in questions] == ["TKT-00010"]
    assert questions[0]["status"] == "resolved"


def test_pending_customer_is_a_routing_candidate():
    """The status whose entire purpose is "waiting for the citizen's answer" was
    missing from the candidate set, so every answer to a parked follow-up
    spawned a new ticket."""
    assert "pending_customer" in OPEN_STATUSES
    assert "pending_customer" in ADDRESSABLE_STATUSES


def test_appending_to_a_finished_ticket_is_audited_but_does_not_change_status():
    """The user's decision: append and flag, never auto-close or auto-reopen —
    "Yes it is" and "No it isn't" are indistinguishable to a router, and only a
    human should decide which reopens work."""
    db = _db(tickets=[_ticket("t-10", "TKT-00010", status="closed")],
             messages={"t-10": [_msg("outbound", "Is this resolved?")]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent(index=0))):
        _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-2"))

    db.add_event.assert_awaited_once()
    ticket_id, payload = db.add_event.await_args.args
    assert ticket_id == "t-10"
    assert payload["eventType"] == "ticket.reply_after_resolution"
    assert payload["meta"]["status"] == "closed"
    # No status change anywhere.
    db.update_ticket.assert_not_called()


def test_appending_to_an_open_ticket_writes_no_flag():
    db = _db(tickets=[_ticket("t-10", "TKT-00010", status="in_progress")],
             messages={"t-10": [_msg("outbound", "Is this resolved?")]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent(index=0))):
        _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-3"))

    db.add_event.assert_not_called()


# --- Rung 0: the message they replied to -----------------------------------

def test_a_reply_to_our_own_message_resolves_to_its_ticket_exactly():
    """Cause 3's fix: we now record the provider id of what we send, so a
    swipe-reply resolves with no judgment at all."""
    db = _db(tickets=[_ticket("t-10", "TKT-00010", status="resolved")])
    db.find_message_by_channel_id = AsyncMock(return_value={"ticket_id": "t-10"})

    with patch("app.tickets.intake.assess_inbound", AsyncMock()) as assess:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes it is",
            in_reply_to="wamid.OURS", channel_identity_type="phone",
            channel_identity_value="+91900", trace_id="tr-4"))

    assert stub == {"id": "t-10", "ticketNumber": "TKT-00010"}
    # Free rung: no LLM call at all.
    assess.assert_not_called()


def test_a_reply_to_the_original_complaint_still_resolves():
    """Feature 19's behaviour, preserved: the citizen swipe-replied to their own
    first message rather than to one of ours."""
    db = _db(tickets=[_ticket("t-7", "TKT-00007", origin_message_id="wamid.THEIRS")])

    with patch("app.tickets.intake.assess_inbound", AsyncMock()):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="It happens around 11PM",
            in_reply_to="wamid.THEIRS", channel_identity_type="phone",
            channel_identity_value="+91900", trace_id="tr-5"))

    assert stub == {"id": "t-7", "ticketNumber": "TKT-00007"}


# --- Rung 1: a typed ticket reference wins over the reply-to ---------------

def test_a_typed_ticket_number_beats_the_thread_they_replied_in():
    """The user's decision on the conflict rule: typing TKT-00099 is a
    deliberate statement of intent, while replying in a thread is often just
    "whichever chat was open"."""
    db = _db(tickets=[_ticket("t-10", "TKT-00010"), _ticket("t-99", "TKT-00099")])
    db.find_message_by_channel_id = AsyncMock(return_value={"ticket_id": "t-10"})

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Actually this is about TKT-00099",
        in_reply_to="wamid.OURS", channel_identity_type="phone",
        channel_identity_value="+91900", trace_id="tr-6"))

    assert stub == {"id": "t-99", "ticketNumber": "TKT-00099"}


def test_an_unknown_ticket_number_is_ignored_rather_than_obeyed():
    """A citizen quoting a number we have no record of must not stop routing —
    the message still gets assessed on its content."""
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "No power")]})

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(is_new_complaint=True))), \
         patch("app.tickets.intake._match_against_open_tickets", AsyncMock(return_value=None)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp",
            raw_text="TKT-88888 water logging in Velachery",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-7"))

    assert stub["id"] == "new-1"


# --- Rung 3: the intake guard, now gated on having asked -------------------

def test_a_bare_yes_no_longer_hijacks_a_stub_we_asked_nothing_on():
    """Cause 2. The stub is mid-intake and "Yes" is structurally an intake
    answer — but we never asked it anything, so it must not claim the message."""
    db = _db(tickets=[_ticket("t-14", "TKT-00014")],
             messages={"t-14": [_msg("inbound", "No power")]})   # no outbound at all

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes it is",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-8"))

    assert "id" not in stub          # parked, not attached to TKT-00014
    assert stub["unrouted"] is True


def test_an_intake_answer_does_reach_the_stub_that_asked_for_it():
    """The Feature 20 behaviour that must survive: the citizen is answering our
    intake question, and this is the only rung that can tell."""
    db = _db(tickets=[_ticket("t-16", "TKT-00016")],
             messages={"t-16": [_msg("outbound", "What is your name?", is_intake_request=1)]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Nithya",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-9"))

    assert stub == {"id": "t-16", "ticketNumber": "TKT-00016"}


def test_a_categorised_ticket_is_never_treated_as_mid_intake():
    db = _db(tickets=[_ticket("t-16", "TKT-00016", category="billing")],
             messages={"t-16": [_msg("outbound", "What is your name?", is_intake_request=1)]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Nithya",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-10"))

    assert "id" not in stub


def test_two_stubs_both_awaiting_intake_are_not_guessed_between():
    db = _db(tickets=[_ticket("t-1", "TKT-00001"), _ticket("t-2", "TKT-00002")],
             messages={
                 "t-1": [_msg("outbound", "What is your name?", is_intake_request=1)],
                 "t-2": [_msg("outbound", "What is your name?", is_intake_request=1)],
             })

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Nithya",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-11"))

    assert "id" not in stub


# --- Rung 4: a new complaint ----------------------------------------------

def test_a_new_complaint_creates_a_ticket_after_the_duplicate_check():
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "No power")]})

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(is_new_complaint=True))), \
         patch("app.tickets.intake._match_against_open_tickets",
               AsyncMock(return_value=None)) as dedup:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Water logging in Velachery",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-12"))

    assert stub["id"] == "new-1"
    # Feature 22 still gets its say — a new complaint may be a duplicate.
    dedup.assert_awaited_once()


def test_a_new_complaint_that_the_duplicate_check_claims_is_not_recreated():
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "No power")]})

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(is_new_complaint=True))), \
         patch("app.tickets.intake._match_against_open_tickets",
               AsyncMock(return_value={"id": "t-1", "ticketNumber": "TKT-00001"})):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Still no power",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-13"))

    assert stub == {"id": "t-1", "ticketNumber": "TKT-00001"}
    db.create_ticket.assert_not_called()


def test_a_terminal_ticket_is_not_offered_to_the_duplicate_check():
    """Attribution may reach a closed ticket; DUPLICATION of a new complaint
    against one must not — a new problem is not a duplicate of finished work."""
    db = _db(tickets=[_ticket("t-9", "TKT-00009", status="closed")],
             messages={"t-9": [_msg("inbound", "Old complaint")]})

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(is_new_complaint=True))), \
         patch("app.tickets.intake._match_against_open_tickets", AsyncMock()) as dedup:
        _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Water logging in Velachery",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-14"))

    dedup.assert_not_called()


# --- Rung 5: unattributable, and not a complaint --------------------------

def test_an_unattributable_acknowledgement_creates_no_ticket_and_asks():
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "No power")]})

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(reason="pure acknowledgement"))):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="You are correct",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-15"))

    assert "id" not in stub
    assert stub["ask"] == ASK_FOR_REFERENCE
    assert stub["escalated"] is False
    db.create_ticket.assert_not_called()
    # The citizen's words are STORED — a dropped message is invisible to
    # everyone, which is worse than a misroute an agent can fix.
    db.create_unrouted_message.assert_awaited_once()
    parked = db.create_unrouted_message.await_args.args[0]
    assert parked["content"] == "You are correct"
    assert parked["status"] == "pending"
    assert parked["askCount"] == 1


def test_a_second_unroutable_message_escalates_instead_of_asking_again():
    """"Please send your ticket number" -> "I don't have it" is also
    unroutable, and asking again would loop forever."""
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "No power")]}, ask_count=1)

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="I don't have it",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-16"))

    assert stub["ask"] is None
    assert stub["escalated"] is True
    assert db.create_unrouted_message.await_args.args[0]["status"] == "escalated"


def test_routing_survives_the_unrouted_store_itself_failing():
    """Nothing about a citizen's message may raise. If even parking fails we log
    loudly and still return a clean decision."""
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "No power")]})
    db.create_unrouted_message = AsyncMock(side_effect=RuntimeError("db down"))

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="ok",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-17"))

    assert stub["unrouted"] is True
    assert stub["unroutedId"] is None


# --- First contact --------------------------------------------------------

def test_a_first_complaint_from_an_unknown_contact_creates_a_ticket():
    db = _db(tickets=[], identity=None)

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(is_new_complaint=True))):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91777", "whatsapp", raw_text="No power in my area",
            channel_identity_type="phone", channel_identity_value="+91777", trace_id="tr-18"))

    assert stub == {"id": "new-1", "ticketNumber": "TKT-99999"}


def test_a_bare_greeting_from_an_unknown_contact_creates_no_ticket():
    """The one change made to the user's rule 1 ("first message, no check"):
    "Hi" would otherwise become a permanent ticket that reporting has to explain
    forever."""
    db = _db(tickets=[], identity=None)

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(reason="greeting"))):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91777", "whatsapp", raw_text="Hi",
            channel_identity_type="phone", channel_identity_value="+91777", trace_id="tr-19"))

    assert "id" not in stub
    db.create_ticket.assert_not_called()


def test_a_first_contact_still_gets_a_ticket_when_the_judgment_is_unavailable():
    """A lost first complaint is far worse than a junk row — the same
    one-sided bias every LLM-assisted decision in this pipeline takes."""
    db = _db(tickets=[], identity=None)

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=None)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91777", "whatsapp", raw_text="Hi",
            channel_identity_type="phone", channel_identity_value="+91777", trace_id="tr-20"))

    assert stub["id"] == "new-1"


# --- The reply window -----------------------------------------------------

def test_a_stale_question_is_not_offered_as_a_candidate():
    """3 days by default (configurable). A "yes" arriving months after we asked
    is not an answer — the citizen has long forgotten the question."""
    db = _db(tickets=[_ticket("t-10", "TKT-00010", status="resolved")],
             messages={"t-10": [_msg("outbound", "Is this resolved?",
                                     created_at="2020-01-01 00:00:00")]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())) as assess:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes it is",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-21"))

    assert assess.await_args.args[0] == []   # nothing outstanding to answer
    assert "id" not in stub                  # so it is parked, not guessed at


def test_the_reply_window_is_tenant_configurable():
    db = _db(tickets=[_ticket("t-10", "TKT-00010", status="resolved")],
             messages={"t-10": [_msg("outbound", "Is this resolved?",
                                     created_at="2020-01-01 00:00:00")]})
    # A very wide window brings the same stale question back into scope.
    db.get_tenant_config = AsyncMock(return_value={"generalSettings": {"replyWindowDays": 100000}})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())) as assess:
        _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes it is",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-22"))

    assert [q["ticketNumber"] for q in assess.await_args.args[0]] == ["TKT-00010"]


# --- LLM unavailable ------------------------------------------------------

def test_an_llm_outage_asks_rather_than_guessing_a_ticket():
    """The pre-Feature-24 fallbacks ("WhatsApp appends to a sole open ticket")
    were themselves guesses, and one of them is how the reported misroute
    happened. An outage now costs a clarifying question."""
    db = _db(tickets=[_ticket("t-14", "TKT-00014")],
             messages={"t-14": [_msg("inbound", "No power")]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=None)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Yes it is",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-23"))

    assert "id" not in stub


def test_an_llm_outage_still_routes_a_structural_intake_answer():
    """One rung needs no judgment: we asked an intake question on exactly one
    mid-intake stub, and this message is form data."""
    db = _db(tickets=[_ticket("t-16", "TKT-00016")],
             messages={"t-16": [_msg("outbound", "What is your name?", is_intake_request=1)]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=None)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Nithya",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-24"))

    assert stub == {"id": "t-16", "ticketNumber": "TKT-00016"}


def test_an_llm_outage_still_opens_a_ticket_for_prose():
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "Old complaint")]})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=None)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp",
            raw_text="Sewage overflowing on Lattice Bridge Road since Monday",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-25"))

    assert stub["id"] == "new-1"


# --- Feature 22's duplicate question, still reachable from rung 4 ---------

def test_an_unclear_duplicate_still_creates_a_ticket_and_flags_the_suspicion():
    """Carried over from Feature 22: when the duplicate check cannot tell, a
    ticket IS created and the suspicion recorded, so the citizen is asked rather
    than a heuristic silently merging or duplicating."""
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "Water logging in Madambakkam")]})

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(is_new_complaint=True))), \
         patch("app.tickets.intake.match_open_ticket",
               AsyncMock(return_value={"index": 0, "verdict": "unclear",
                                       "reason": "no location given"})):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Water logging again",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-28"))

    assert stub["id"] == "new-1"
    assert stub["suspectedDuplicateOf"]["ticketNumber"] == "TKT-00001"
    # ...and recorded on the ticket itself, so an agent can settle it even if the
    # citizen never answers.
    events = [c.args for c in db.add_event.await_args_list]
    assert any(payload["eventType"] == "ticket.possible_duplicate" for _, payload in events)


def test_routing_survives_a_failed_suspicion_write():
    """The audit write is best-effort — routing must not fail over it."""
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "Water logging in Madambakkam")]})
    db.add_event = AsyncMock(side_effect=RuntimeError("db down"))

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(is_new_complaint=True))), \
         patch("app.tickets.intake.match_open_ticket",
               AsyncMock(return_value={"index": 0, "verdict": "unclear", "reason": "x"})):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+91900", "whatsapp", raw_text="Water logging again",
            channel_identity_type="phone", channel_identity_value="+91900", trace_id="tr-29"))

    assert stub["id"] == "new-1"


# --- The Feature 20 regression, end to end -------------------------------

def test_one_complaint_plus_three_intake_answers_produces_exactly_one_ticket():
    """The Feature 20 bug (one citizen, three messages, three tickets) must stay
    fixed under the new ladder. The stub asks for details and each answer routes
    back to it — now specifically because it is the stub that ASKED."""
    stub_ticket = _ticket("t-16", "TKT-00016")
    timeline = [_msg("inbound", "No power in my area"),
                _msg("outbound", "Please share your name, email and customer id",
                     is_intake_request=1)]
    db = _db(tickets=[stub_ticket], messages={"t-16": timeline})

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        for answer in ("Nithya", "nithya@gmail.com", "56784567"):
            resolved = _run(ensure_ticket_stub(
                db, "t1", "whatsapp:+919000000000", "whatsapp", raw_text=answer,
                channel_identity_type="phone", channel_identity_value="+919000000000",
                trace_id=f"tr-{answer}"))
            assert resolved == {"id": "t-16", "ticketNumber": "TKT-00016"}, answer

    db.create_ticket.assert_not_called()


# --- Email specifics ------------------------------------------------------

def test_quoted_text_is_stripped_before_the_message_is_judged():
    """An email reply carries our whole question quoted underneath. Judging the
    raw body would see our own words and answer yes to almost anything."""
    db = _db(tickets=[_ticket("t-10", "TKT-00010", status="resolved")],
             messages={"t-10": [_msg("outbound", "Is this resolved?")]})
    raw = ("Yes it is\n\n"
           "On Mon, 4 Aug 2026 at 09:12, UniServe wrote:\n"
           "> Is this resolved? Your complaint about water logging in Madambakkam")

    with patch("app.tickets.intake.assess_inbound",
               AsyncMock(return_value=_intent(index=0))) as assess:
        _run(ensure_ticket_stub(
            db, "t1", "email:x@y.com", "email", raw_text=raw,
            channel_identity_type="email", channel_identity_value="x@y.com", trace_id="tr-26"))

    assert assess.await_args.args[1] == "Yes it is"


def test_the_stored_message_keeps_the_quoted_text_even_though_judging_does_not():
    """Only the JUDGMENT uses the stripped text. What gets parked (or persisted)
    is what the citizen actually sent, quotes and all — an agent resolving it
    needs the full context."""
    db = _db(tickets=[_ticket("t-1", "TKT-00001")],
             messages={"t-1": [_msg("inbound", "No power")]})
    raw = "ok\n\n> Please confirm"

    with patch("app.tickets.intake.assess_inbound", AsyncMock(return_value=_intent())):
        _run(ensure_ticket_stub(
            db, "t1", "email:x@y.com", "email", raw_text=raw,
            channel_identity_type="email", channel_identity_value="x@y.com", trace_id="tr-27"))

    assert db.create_unrouted_message.await_args.args[0]["content"] == raw
