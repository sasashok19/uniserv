"""Unit tests for ticket stub lifecycle (Feature 06 x 12 x 15)."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.dedup.service import OPEN_STATUSES
from app.tickets.intake import (
    ensure_ticket_stub,
    extract_ticket_number,
    looks_like_intake_answer,
    update_ticket_identity,
)


def _run(coro):
    return asyncio.run(coro)


# `match_open_ticket` verdicts (Feature 22). It replaced Feature 18's boolean
# `is_same_topic`: one call judges the new message against ALL of the citizen's
# open tickets and names which one it concerns, so the result carries an index
# as well as a verdict, and can say "unclear" rather than being forced to guess.
_SAME = {"index": 0, "verdict": "same", "reason": "same problem, same place"}
_DIFFERENT = {"index": None, "verdict": "different", "reason": "different problem"}
_UNCLEAR = {"index": 0, "verdict": "unclear", "reason": "new message omits the location"}


def test_ensure_ticket_stub_reuses_existing_ticket_for_thread():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "t-1", "ticket_number": "TKT-00001"}])
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(db, "t1", "email:citizen@example.com", "email", trace_id="tr-1"))

    assert stub == {"id": "t-1", "ticketNumber": "TKT-00001"}
    db.create_ticket.assert_not_called()
    db.list_tickets.assert_awaited_once_with(
        "t1", threadId="email:citizen@example.com", status=OPEN_STATUSES, trace_id="tr-1")


def test_ensure_ticket_stub_creates_bare_stub_when_none_exists():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])
    db.create_ticket = AsyncMock(return_value={"id": "t-2", "ticketNumber": "TKT-00002"})

    stub = _run(ensure_ticket_stub(db, "t1", "email:new@example.com", "email", trace_id="tr-2"))

    assert stub == {"id": "t-2", "ticketNumber": "TKT-00002"}
    payload = db.create_ticket.await_args.args[0]
    assert payload["threadId"] == "email:new@example.com"
    assert payload["channelOrigin"] == "email"
    assert payload["identityStatus"] == "pending"
    assert payload["status"] == "open"


def test_ensure_ticket_stub_prioritizes_subject_ticket_reference_over_thread():
    """A reply whose subject echoes back "[Ticket TKT-00042]" must resolve to
    THAT ticket even if thread matching would say otherwise — this is the
    fix for citizens replying to an old thread with unrelated quoting."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "t-42", "ticket_number": "TKT-00042"}])
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(
        db, "t1", "email:citizen@example.com", "email",
        subject="Re: My complaint [Ticket TKT-00042]", trace_id="tr-3"))

    assert stub == {"id": "t-42", "ticketNumber": "TKT-00042"}
    db.list_tickets.assert_awaited_once_with("t1", ticketNumber="TKT-00042", trace_id="tr-3")
    db.create_ticket.assert_not_called()


def test_ensure_ticket_stub_falls_back_to_thread_when_subject_ticket_not_found():
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[[], [{"id": "t-1", "ticket_number": "TKT-00001"}]])
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(
        db, "t1", "email:citizen@example.com", "email",
        subject="[Ticket TKT-99999]", trace_id="tr-4"))

    assert stub == {"id": "t-1", "ticketNumber": "TKT-00001"}
    assert db.list_tickets.await_count == 2


def test_ensure_ticket_stub_persists_origin_message_id_on_create():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])
    db.create_ticket = AsyncMock(return_value={"id": "t-3", "ticketNumber": "TKT-00003"})

    _run(ensure_ticket_stub(
        db, "t1", "email:msg-xyz", "email", origin_message_id="msg-xyz", trace_id="tr-5"))

    payload = db.create_ticket.await_args.args[0]
    assert payload["originMessageId"] == "msg-xyz"


def test_extract_ticket_number_finds_reference_anywhere_in_subject():
    assert extract_ticket_number("Re: Billing issue [Ticket TKT-00042]") == "TKT-00042"
    assert extract_ticket_number("No reference here") is None
    assert extract_ticket_number(None) is None


def test_extract_ticket_number_also_matches_message_body():
    """Feature 17: a channel with no subject line (WhatsApp) can still get a
    deterministic match if the citizen mentions the ticket number directly —
    e.g. answering a disambiguation prompt, or following up unprompted."""
    assert extract_ticket_number("Following up on TKT-00099, any update?") == "TKT-00099"


# ---------------------------------------------------------------------------
# Feature 17: WhatsApp threading/dedup fix.
#
# Bug: WhatsApp's thread key (`whatsapp:<phone>`) is identical for every
# message that number ever sends, and the threadId lookup applied no status
# filter — so a citizen whose ticket had already been resolved, texting
# weeks later about something unrelated, was silently appended to the old,
# resolved ticket. These tests cover the fix: the threadId fallback now
# requires OPEN status, and (for non-email channels) falls back further to
# an identity + open-ticket-count resolution.
# ---------------------------------------------------------------------------

def test_ensure_ticket_stub_does_not_reuse_resolved_whatsapp_ticket():
    """The exact reported bug: an old RESOLVED ticket must not be silently
    reused just because it shares the same (permanent, per-phone) thread key."""
    db = AsyncMock()
    # 1st call: identityId lookup for open tickets -> empty (the citizen's
    # only ticket is the resolved one, which isn't "open").
    # 2nd call: threadId lookup (fallback for the not-yet-linked window) ->
    # also empty -- the resolved ticket is correctly excluded by the status filter.
    db.list_tickets = AsyncMock(side_effect=[[], []])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00050"})

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+919876543210", "whatsapp",
        raw_text="Now my new water heater is broken too", channel_identity_type="phone",
        channel_identity_value="+919876543210", trace_id="tr-6"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00050"}
    db.create_ticket.assert_awaited_once()
    first_call = db.list_tickets.await_args_list[0]
    assert first_call.kwargs["identityId"] == "m-1"
    assert first_call.kwargs["status"] == OPEN_STATUSES
    second_call = db.list_tickets.await_args_list[1]
    assert second_call.kwargs["threadId"] == "whatsapp:+919876543210"
    assert second_call.kwargs["status"] == OPEN_STATUSES


def test_ensure_ticket_stub_whatsapp_appends_to_sole_open_ticket():
    """A genuine follow-up (identity has exactly one currently-open ticket)
    still gets appended, not duplicated — resolved via identity FIRST, never
    reaching the threadId fallback at all."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "t-open-1", "ticket_number": "TKT-00060"}])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-2"})
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+919876543211", "whatsapp",
        raw_text="Still waiting on this", channel_identity_type="phone",
        channel_identity_value="+919876543211", trace_id="tr-7"))

    assert stub == {"id": "t-open-1", "ticketNumber": "TKT-00060"}
    db.create_ticket.assert_not_called()
    db.list_tickets.assert_awaited_once_with(
        "t1", identityId="m-2", status=OPEN_STATUSES, sortBy="createdAt", sortDir="desc", trace_id="tr-7")


# ---------------------------------------------------------------------------
# Feature 18: even with the reorder fix, "exactly one open ticket" was still
# an UNCONDITIONAL append — count alone can't tell a genuine follow-up apart
# from an unrelated second complaint, and a keyword classifier gives no
# signal either way for text like "Put not closed" (matches no category).
# These test the real content-level check that closes that gap.
# ---------------------------------------------------------------------------

def test_ensure_ticket_stub_creates_new_when_sole_open_ticket_is_a_different_topic():
    """The exact reported bug, reproduced: "No power" (existing ticket) vs
    "Put not closed" (new message) — same identity, one open ticket, but a
    different complaint."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[
        [{"id": "t-power", "ticket_number": "TKT-00090", "category": "outage"}],
        [],  # thread-key lookup after the judgment says "different"
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-ashok"})
    db.get_messages = AsyncMock(return_value=[
        {"direction": "inbound", "content": "No power"},
    ])
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00091"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939012727", "whatsapp",
            raw_text="Put not closed", channel_identity_type="phone",
            channel_identity_value="+918939012727", trace_id="tr-18a"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00091"}
    candidates, new_text = match.await_args.args
    assert new_text == "Put not closed"
    assert candidates == [{"ticketNumber": "TKT-00090", "text": "No power", "category": "outage"}]


def test_ensure_ticket_stub_appends_when_sole_open_ticket_is_the_same_topic():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-power", "ticket_number": "TKT-00090", "category": "outage"},
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-ashok"})
    db.get_messages = AsyncMock(return_value=[
        {"direction": "inbound", "content": "No power"},
    ])
    db.create_ticket = AsyncMock()

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_SAME)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939012727", "whatsapp",
            raw_text="Still no power, any update?", channel_identity_type="phone",
            channel_identity_value="+918939012727", trace_id="tr-18b"))

    assert stub == {"id": "t-power", "ticketNumber": "TKT-00090"}
    db.create_ticket.assert_not_called()


def test_ensure_ticket_stub_appends_when_same_topic_check_unavailable():
    """Best-effort: if the LLM check itself is unavailable/fails (returns
    None), fall back to the safe default (append) rather than blocking or
    guessing wrong."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-power", "ticket_number": "TKT-00090", "category": "outage"},
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-ashok"})
    db.get_messages = AsyncMock(return_value=[{"direction": "inbound", "content": "No power"}])
    db.create_ticket = AsyncMock()

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=None)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939012727", "whatsapp",
            raw_text="Put not closed", channel_identity_type="phone",
            channel_identity_value="+918939012727", trace_id="tr-18c"))

    assert stub == {"id": "t-power", "ticketNumber": "TKT-00090"}
    db.create_ticket.assert_not_called()


def test_ensure_ticket_stub_skips_same_topic_check_when_no_message_history():
    """No fetchable original complaint text (e.g. get_messages failed or the
    ticket somehow has no inbound message yet) -- skip the LLM call
    entirely and fall back to append, rather than comparing against nothing."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-power", "ticket_number": "TKT-00090", "category": "outage"},
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-ashok"})
    db.get_messages = AsyncMock(return_value=[])
    db.create_ticket = AsyncMock()

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock()) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939012727", "whatsapp",
            raw_text="Put not closed", channel_identity_type="phone",
            channel_identity_value="+918939012727", trace_id="tr-18d"))

    assert stub == {"id": "t-power", "ticketNumber": "TKT-00090"}
    match.assert_not_called()


def test_ensure_ticket_stub_multiple_open_tickets_are_all_judged_not_given_up_on():
    """Feature 22 replaces Feature 17's "2+ open tickets, don't guess -> always
    a new ticket". That rule is what let the reported email case through: a
    stale unconfirmed stub was open alongside the real one, so the second
    email never reached any topic check at all. Every open ticket is now put
    to the SAME single judgment, and a "different" verdict still means a new
    ticket — the safe outcome is preserved, it is just now a decision rather
    than a refusal to decide."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[
        [{"id": "t-open-1", "ticket_number": "TKT-00061"}, {"id": "t-open-2", "ticket_number": "TKT-00062"}],
        [],  # thread-key lookup after the judgment says "different"
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-3"})
    db.get_messages = AsyncMock(return_value=[{"direction": "inbound", "content": "No power"}])
    db.create_ticket = AsyncMock(return_value={"id": "t-new-2", "ticketNumber": "TKT-00070"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+919876543212", "whatsapp",
            raw_text="A completely different issue", channel_identity_type="phone",
            channel_identity_value="+919876543212", trace_id="tr-8"))

    assert stub == {"id": "t-new-2", "ticketNumber": "TKT-00070"}
    # BOTH open tickets were offered to the model, in one call — not one call each.
    candidates = match.await_args.args[0]
    assert [c["ticketNumber"] for c in candidates] == ["TKT-00061", "TKT-00062"]
    match.assert_awaited_once()


def test_ensure_ticket_stub_routes_to_the_matched_ticket_among_several_open():
    """The reported email case, generalised: the citizen has two open tickets
    and the new message continues the SECOND one."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-power", "ticket_number": "TKT-00061", "category": "outage"},
        {"id": "t-water", "ticket_number": "TKT-00062", "category": "water"},
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-3"})
    db.get_messages = AsyncMock(return_value=[{"direction": "inbound", "content": "some complaint"}])
    db.create_ticket = AsyncMock()

    picked = {"index": 1, "verdict": "same", "reason": "same water logging"}
    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=picked)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+919876543212", "whatsapp",
            raw_text="Still water logging, no action taken", channel_identity_type="phone",
            channel_identity_value="+919876543212", trace_id="tr-8b"))

    assert stub == {"id": "t-water", "ticketNumber": "TKT-00062"}
    db.create_ticket.assert_not_called()


def test_ensure_ticket_stub_unclear_creates_a_ticket_and_flags_the_suspicion():
    """The scenario that decided this design: "water logging" arriving while
    "water logging in Madambakkam" is open. Merging would be a guess, so a
    ticket IS created — but flagged, so the conversation asks the citizen
    instead of a heuristic deciding for them. Nothing is merged until they
    answer, so the cost of being wrong here is one extra question."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-mdk", "ticket_number": "TKT-00042", "category": "water"},
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-9"})
    db.get_messages = AsyncMock(
        return_value=[{"direction": "inbound", "content": "Water logging in Madambakkam"}])
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00043"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_UNCLEAR)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+919876543212", "whatsapp",
            raw_text="Water logging", channel_identity_type="phone",
            channel_identity_value="+919876543212", trace_id="tr-8c"))

    assert stub["id"] == "t-new"
    assert stub["suspectedDuplicateOf"]["ticketNumber"] == "TKT-00042"
    assert stub["suspectedDuplicateOf"]["summary"] == "Water logging in Madambakkam"
    db.create_ticket.assert_awaited_once()


def test_ensure_ticket_stub_whatsapp_brand_new_number_creates_new_without_identity_lookup_crash():
    """A phone number never seen before — find_by_phone returns None, and the
    identity branch must be skipped cleanly rather than erroring."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])
    db.find_by_phone = AsyncMock(return_value=None)
    db.create_ticket = AsyncMock(return_value={"id": "t-brand-new", "ticketNumber": "TKT-00071"})

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+919800000099", "whatsapp",
        raw_text="Meter not working", channel_identity_type="phone",
        channel_identity_value="+919800000099", trace_id="tr-9"))

    assert stub == {"id": "t-brand-new", "ticketNumber": "TKT-00071"}
    db.list_tickets.assert_awaited_once()  # only the threadId lookup — no identityId lookup possible


def test_email_with_no_open_tickets_still_creates_a_new_one():
    """Email now DOES consult the identity branch (Feature 22 — see the two
    tests below for why), so this guards the ordinary case: nothing open for
    this sender means nothing to match against, and a new ticket is created
    exactly as before."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])
    db.find_by_email = AsyncMock(return_value={"master_id": "m-email"})
    db.create_ticket = AsyncMock(return_value={"id": "t-email-new", "ticketNumber": "TKT-00080"})

    stub = _run(ensure_ticket_stub(
        db, "t1", "email:msg-abc", "email",
        raw_text="My bill is wrong", channel_identity_type="email",
        channel_identity_value="citizen@example.com", trace_id="tr-10"))

    assert stub == {"id": "t-email-new", "ticketNumber": "TKT-00080"}


# ---------------------------------------------------------------------------
# Feature 22: the reported EMAIL case. Two separately-composed emails, minutes
# apart, both "water logging in my area" -> two tickets (TKT-00020/21) on top
# of a stale unconfirmed stub (TKT-00019). Root cause: email skipped the
# identity branch entirely (`if channel != "email"`), so no dedup of any kind
# ran on it — every unthreaded email was a new complaint by construction.
# ---------------------------------------------------------------------------

def test_second_email_on_the_same_topic_merges_instead_of_creating_a_ticket():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-20", "ticket_number": "TKT-00020", "category": "other"},
    ])
    db.find_by_email = AsyncMock(return_value={"master_id": "m-sasashok"})
    db.get_messages = AsyncMock(return_value=[{
        "direction": "inbound",
        "content": "Water logging in my area. No proper response event after complaining "
                   "multiple times. Waste of time and pathetic service.",
    }])
    db.create_ticket = AsyncMock()

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_SAME)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "email:<msg-B@mail.gmail.com>", "email",
            raw_text="Water logging in my area. Please address it.",
            channel_identity_type="email", channel_identity_value="sasashok19@gmail.com",
            trace_id="tr-22a"))

    assert stub == {"id": "t-20", "ticketNumber": "TKT-00020"}
    db.create_ticket.assert_not_called()


def test_a_genuinely_new_email_complaint_still_gets_its_own_ticket():
    """The Feature 15 property this must not break: a brand-new email is a new
    complaint unless the content says otherwise. It is now the MODEL saying
    otherwise, rather than a shared thread key — which is what made the old
    `email:<address>` fallback collapse unrelated complaints together."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[
        [{"id": "t-20", "ticket_number": "TKT-00020", "category": "other"}],
        [],  # thread-key lookup after the judgment says "different"
    ])
    db.find_by_email = AsyncMock(return_value={"master_id": "m-sasashok"})
    db.get_messages = AsyncMock(return_value=[{"direction": "inbound", "content": "Water logging in my area"}])
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00022"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "email:<msg-C@mail.gmail.com>", "email",
            raw_text="My electricity bill for March is double the usual amount",
            channel_identity_type="email", channel_identity_value="sasashok19@gmail.com",
            trace_id="tr-22b"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00022"}


def test_email_falls_back_to_a_new_ticket_when_the_judgment_is_unavailable():
    """Best-effort, but the safe direction is channel-specific: an LLM outage
    must not start merging a citizen's separate emails together, so email
    keeps its long-standing "new email = new complaint" default. (WhatsApp's
    default stays "append" — its thread key really is per-conversation.)"""
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[
        [{"id": "t-20", "ticket_number": "TKT-00020", "category": "other"}],
        [],
    ])
    db.find_by_email = AsyncMock(return_value={"master_id": "m-sasashok"})
    db.get_messages = AsyncMock(return_value=[{"direction": "inbound", "content": "Water logging in my area"}])
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00023"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=None)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "email:<msg-D@mail.gmail.com>", "email",
            raw_text="Water logging in my area. Please address it.",
            channel_identity_type="email", channel_identity_value="sasashok19@gmail.com",
            trace_id="tr-22c"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00023"}


def test_ensure_ticket_stub_explicit_reference_in_whatsapp_body_wins_over_open_count():
    """A citizen who mentions a ticket number directly (e.g. answering a
    disambiguation prompt) resolves to THAT ticket, bypassing the
    identity/open-count heuristic entirely — and works regardless of that
    ticket's status, same as email's subject-reference behaviour."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "t-referenced", "ticket_number": "TKT-00042"}])
    db.find_by_phone = AsyncMock()
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+919876543213", "whatsapp",
        raw_text="This is about TKT-00042, any update?", channel_identity_type="phone",
        channel_identity_value="+919876543213", trace_id="tr-11"))

    assert stub == {"id": "t-referenced", "ticketNumber": "TKT-00042"}
    db.list_tickets.assert_awaited_once_with("t1", ticketNumber="TKT-00042", trace_id="tr-11")
    db.find_by_phone.assert_not_called()
    db.create_ticket.assert_not_called()


# ---------------------------------------------------------------------------
# Feature 20: an intake ANSWER (name / email / service id / pin code) is not a
# complaint at all, so Feature 18's same-topic judgment — which asks "does
# this describe the same problem?" — can only ever answer "no" for it, and did:
# live-tested, +918939014142 sent "No power in my area" (stub TKT-00016) and
# then two intake replies, which became TKT-00017 and TKT-00018.
# ---------------------------------------------------------------------------

def _intake_stub_db(open_tickets, new_ticket=None):
    """A db stub that answers the identity lookup with `open_tickets` and the
    thread-key lookup with nothing. Distinguishing the two matters: a single
    `return_value` is replayed for BOTH, so a test expecting a new ticket would
    silently resolve to the very ticket the judgment just rejected."""
    async def list_tickets(tenant_id, trace_id=None, **filters):
        return list(open_tickets) if "identityId" in filters else []

    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=list_tickets)
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-nithya"})
    db.get_messages = AsyncMock(return_value=[{"direction": "inbound", "content": "No power in my area"}])
    db.create_ticket = AsyncMock(return_value=new_ticket or {"id": "t-new", "ticketNumber": "TKT-99999"})
    return db


# The stub TKT-00016 as db-writer returns it while intake is still in
# progress: identity linked, but no category (no complaint filed on it yet).
_OPEN_STUB = {"id": "t-16", "ticket_number": "TKT-00016", "category": None}


def test_whatsapp_intake_answer_stays_on_the_in_intake_stub():
    """Message 2 of the reported transcript: name + email + service id. It
    names no problem, so the topic check would (correctly, by its own
    definition) say "different topic" — the guard must stop it being asked."""
    db = _intake_stub_db([_OPEN_STUB])

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939014142", "whatsapp",
            raw_text="Nithya\nNithya@gmaill.com\n56784567",
            channel_identity_type="phone", channel_identity_value="+918939014142", trace_id="tr-20a"))

    assert stub == {"id": "t-16", "ticketNumber": "TKT-00016"}
    db.create_ticket.assert_not_called()
    match.assert_not_called()


def test_whatsapp_bare_email_retry_stays_on_the_in_intake_stub():
    """Message 3 of the same transcript: just the corrected email address."""
    db = _intake_stub_db([_OPEN_STUB])

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939014142", "whatsapp",
            raw_text="dharshini.s.raj@gmail.com",
            channel_identity_type="phone", channel_identity_value="+918939014142", trace_id="tr-20b"))

    assert stub == {"id": "t-16", "ticketNumber": "TKT-00016"}
    db.create_ticket.assert_not_called()


def test_whatsapp_intake_answer_finds_the_sole_in_intake_stub_among_several_open_tickets():
    """Self-healing for threads this bug already split: with TKT-00017 open
    alongside the stub, the old code took the ">1 open, don't guess" branch
    and shed yet another ticket per reply. Exactly one ticket is still in
    intake, so there is nothing to guess between."""
    db = _intake_stub_db([
        {"id": "t-17", "ticket_number": "TKT-00017", "category": "other"},
        _OPEN_STUB,
    ])

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+918939014142", "whatsapp",
        raw_text="dharshini.s.raj@gmail.com",
        channel_identity_type="phone", channel_identity_value="+918939014142", trace_id="tr-20c"))

    assert stub == {"id": "t-16", "ticketNumber": "TKT-00016"}
    db.create_ticket.assert_not_called()


def test_whatsapp_new_complaint_still_creates_a_new_ticket_when_a_stub_is_open():
    """The Feature 18 behaviour this guard must not swallow: real complaint
    prose is not intake data, so the topic check still runs and still splits."""
    db = _intake_stub_db([_OPEN_STUB], new_ticket={"id": "t-new", "ticketNumber": "TKT-00019"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939014142", "whatsapp",
            raw_text="Now my water heater is broken too",
            channel_identity_type="phone", channel_identity_value="+918939014142", trace_id="tr-20d"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00019"}
    match.assert_awaited_once()


def test_whatsapp_intake_answer_does_not_hijack_a_categorised_ticket():
    """The guard is scoped to stubs that never had a complaint filed. Once a
    ticket HAS a category, the intake it was created from is finished, so an
    intake-looking message goes back through the normal topic judgment."""
    db = _intake_stub_db(
        [{"id": "t-done", "ticket_number": "TKT-00030", "category": "billing"}],
        new_ticket={"id": "t-new", "ticketNumber": "TKT-00031"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939014142", "whatsapp",
            raw_text="ravi@example.com",
            channel_identity_type="phone", channel_identity_value="+918939014142", trace_id="tr-20e"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00031"}
    match.assert_awaited_once()


def test_whatsapp_intake_answer_with_two_open_stubs_defers_to_the_judgment():
    """Two in-intake stubs is genuinely ambiguous — which one is this answer
    for? — so the structural guard declines and hands the question to the
    Feature 22 judgment rather than picking. Here it says "different", so a new
    ticket is created; the point of the test is that the guard steps aside
    rather than guessing between the two."""
    db = _intake_stub_db(
        [_OPEN_STUB, {"id": "t-16b", "ticket_number": "TKT-00016B", "category": None}],
        new_ticket={"id": "t-new", "ticketNumber": "TKT-00032"})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939014142", "whatsapp",
            raw_text="ravi@example.com",
            channel_identity_type="phone", channel_identity_value="+918939014142", trace_id="tr-20f"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00032"}
    match.assert_awaited_once()


def test_email_intake_answer_also_stays_on_its_in_intake_stub():
    """Feature 22 opened the identity branch to email, so the Feature 20 guard
    now protects email intake replies too — an emailed "Name: Nithya" answering
    our identity request must not become its own ticket either."""
    async def list_tickets(tenant_id, trace_id=None, **filters):
        if "identityId" in filters:
            return [{"id": "t-email-stub", "ticket_number": "TKT-00040", "category": None}]
        return []

    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=list_tickets)
    db.find_by_email = AsyncMock(return_value={"master_id": "m-email"})
    db.create_ticket = AsyncMock()

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock()) as match:
        stub = _run(ensure_ticket_stub(
            db, "t1", "email:msg-abc", "email", raw_text="Name: Nithya",
            channel_identity_type="email", channel_identity_value="nithya@example.com", trace_id="tr-20g"))

    assert stub == {"id": "t-email-stub", "ticketNumber": "TKT-00040"}
    db.create_ticket.assert_not_called()
    match.assert_not_called()  # settled structurally; no LLM call needed


def test_three_message_whatsapp_intake_produces_exactly_one_ticket():
    """The whole reported transcript end to end, against one simulated ticket
    store: complaint, then two intake replies. Before the fix this produced
    TKT-00016/17/18; it must produce one ticket and route both replies to it."""
    tickets = []

    async def list_tickets(tenant_id, trace_id=None, **filters):
        if "originMessageId" in filters or "ticketNumber" in filters:
            return []
        if "identityId" in filters:
            return [t for t in tickets if t["identity_id"] == filters["identityId"]
                    and t["status"] in OPEN_STATUSES]
        return [t for t in tickets if t["thread_id"] == filters.get("threadId")
                and t["status"] in OPEN_STATUSES]

    async def create_ticket(payload, trace_id=None):
        ticket = {"id": f"t-{len(tickets)}", "ticketNumber": f"TKT-{16 + len(tickets):05d}",
                  "ticket_number": f"TKT-{16 + len(tickets):05d}", "thread_id": payload["threadId"],
                  "status": "open", "category": None, "identity_id": None}
        tickets.append(ticket)
        return ticket

    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=list_tickets)
    db.create_ticket = AsyncMock(side_effect=create_ticket)
    db.get_messages = AsyncMock(return_value=[{"direction": "inbound", "content": "No power in my area"}])
    # Message 1 arrives before any identity exists; the stub is linked to one
    # by the conversation turn that follows it (update_ticket_identity), which
    # is what the two later lookups then find.
    db.find_by_phone = AsyncMock(side_effect=[None, {"master_id": "m-1"}, {"master_id": "m-1"}])

    async def route(text):
        return await ensure_ticket_stub(
            db, "t1", "whatsapp:+918939014142", "whatsapp", raw_text=text,
            channel_identity_type="phone", channel_identity_value="+918939014142", trace_id="tr-20i")

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_DIFFERENT)):
        first = _run(route("No power in my area"))
        tickets[0]["identity_id"] = "m-1"                      # the conversation turn links it
        second = _run(route("Nithya\nNithya@gmaill.com\n56784567"))
        third = _run(route("dharshini.s.raj@gmail.com"))

    assert len(tickets) == 1
    assert first == second == third == {"id": "t-0", "ticketNumber": "TKT-00016"}


def test_looks_like_intake_answer_accepts_form_data_in_any_phrasing():
    assert looks_like_intake_answer("Nithya\nNithya@gmaill.com\n56784567") is True
    assert looks_like_intake_answer("dharshini.s.raj@gmail.com") is True
    assert looks_like_intake_answer("Name: Nithya") is True
    assert looks_like_intake_answer("My name is Ravi Kumar") is True
    assert looks_like_intake_answer("Nithya") is True          # bare name, no label at all
    assert looks_like_intake_answer("Service ID 56784567") is True
    assert looks_like_intake_answer("Pin code 600001") is True
    assert looks_like_intake_answer("anonymous") is True


def test_looks_like_intake_answer_accepts_a_reply_to_the_email_typo_question():
    """Feature 20 asks the citizen "did you mean x@gmail.com?" — so the shape
    of the reply it invites ("no, it's ...") has to be recognised, or the
    correction turn itself would spawn the very duplicate ticket this whole
    fix exists to prevent. A negation is only forgiven alongside a concrete
    value; on its own it still reads as complaint content (next test)."""
    assert looks_like_intake_answer("no, dharshini.s.raj@gmail.com") is True
    assert looks_like_intake_answer("No - it is dharshini.s.raj@gmail.com") is True
    assert looks_like_intake_answer("sorry, typo. nithya@gmail.com") is True
    assert looks_like_intake_answer("no its 56784567") is True
    assert looks_like_intake_answer("yes that's correct") is True


def test_negation_alongside_a_value_is_still_rejected_when_it_describes_a_problem():
    """The forgiveness above is scoped to the negation itself — a real
    complaint that happens to contain a number is still a complaint."""
    assert looks_like_intake_answer("no water at 600042") is False
    assert looks_like_intake_answer("no bill received for 12345678") is False
    assert looks_like_intake_answer("no power since 2 days") is False


def test_looks_like_intake_answer_rejects_anything_describing_a_problem():
    """Every one of these is a real message from this repo's own live-testing
    history — the guard must not capture any of them."""
    assert looks_like_intake_answer("No power in my area") is False
    assert looks_like_intake_answer("Put not closed") is False
    assert looks_like_intake_answer("It happens around 11PM") is False
    assert looks_like_intake_answer("Meter not working") is False
    assert looks_like_intake_answer("my phone is not working") is False   # "phone" is a field label
    assert looks_like_intake_answer("Now my new water heater is broken too") is False
    assert looks_like_intake_answer("My bill is wrong, contact me at x@y.com") is False
    assert looks_like_intake_answer("any update?") is False
    assert looks_like_intake_answer("") is False
    assert looks_like_intake_answer(None) is False


def test_looks_like_intake_answer_accepts_a_bare_yes_or_no():
    """The reply to Feature 20's own "did you mean x@gmail.com?" is usually
    one word. If that doesn't route back to the stub that asked, the
    correction turn spawns the duplicate ticket the guard exists to prevent —
    and nobody opens a conversation by texting "yes"."""
    for message in ("Yes", "yes", "No", "ok", "yes please"):
        assert looks_like_intake_answer(message) is True, message


def test_looks_like_intake_answer_handles_real_world_name_and_id_formatting():
    """Names are not ASCII, WhatsApp messages carry emoji, and identifiers get
    typed with spaces in them — each of these was rejected outright by an
    earlier, tidier version of this check."""
    assert looks_like_intake_answer("Ravi Kumar Sharma") is True       # three-part name
    assert looks_like_intake_answer("சித்ரா") is True                    # Tamil (combining marks)
    assert looks_like_intake_answer("José Fernandes") is True          # accented Latin
    assert looks_like_intake_answer("Thanks 🙏 Nithya") is True         # emoji token
    assert looks_like_intake_answer("600 042") is True                 # pin code with a space
    assert looks_like_intake_answer("+91 89390 14142") is True         # grouped phone number
    # The intake form's own numbered prompt invites a long-ish single reply.
    assert looks_like_intake_answer(
        "My name is Nithya and my email is nithya@gmail.com and my id is 56784567") is True


def test_looks_like_intake_answer_rejects_a_terse_one_word_complaint():
    """The bare-name path is the loosest rule here, so the utility/service
    nouns a citizen would use as a one-word complaint are named explicitly as
    statement words — otherwise "Transformer" reads exactly like "Nithya"."""
    for message in ("Streetlight", "Transformer", "Blackout", "Sewage overflow",
                    "Garbage", "Refund", "Wrong reading", "Drainage block"):
        assert looks_like_intake_answer(message) is False, message


def test_update_ticket_identity_patches_identity_fields():
    db = AsyncMock()
    db.update_ticket = AsyncMock(return_value={})

    _run(update_ticket_identity(db, "t-1", "m-1", "confirmed", trace_id="tr-3"))

    db.update_ticket.assert_awaited_once_with(
        "t-1", {"identityId": "m-1", "identityStatus": "confirmed"}, trace_id="tr-3")


def test_update_ticket_identity_writes_extra_fields_alongside_identity():
    """Feature 20: partial intake (a Service/Customer ID) lands on the ticket
    on the turn it's given, not only if/when the complaint is submitted."""
    db = AsyncMock()
    db.update_ticket = AsyncMock(return_value={})

    _run(update_ticket_identity(
        db, "t-16", "m-1", "pending", trace_id="tr-20h", extra_fields={"serviceId": "56784567"}))

    db.update_ticket.assert_awaited_once_with(
        "t-16", {"identityId": "m-1", "identityStatus": "pending", "serviceId": "56784567"}, trace_id="tr-20h")


def test_ensure_ticket_stub_in_reply_to_resolves_directly():
    """Feature 19: a WhatsApp swipe-reply (or email In-Reply-To) whose quoted
    message id matches a ticket's origin_message_id resolves to THAT ticket
    without ever touching the ticket-number/identity/thread checks below it."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "t-14", "ticket_number": "TKT-00014"}])
    db.find_by_phone = AsyncMock()
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+919876543213", "whatsapp",
        raw_text="It happens around 11PM", channel_identity_type="phone",
        channel_identity_value="+919876543213", in_reply_to="wamid.ORIGINAL123",
        trace_id="tr-19"))

    assert stub == {"id": "t-14", "ticketNumber": "TKT-00014"}
    db.list_tickets.assert_awaited_once_with("t1", originMessageId="wamid.ORIGINAL123", trace_id="tr-19")
    db.find_by_phone.assert_not_called()
    db.create_ticket.assert_not_called()


def test_ensure_ticket_stub_in_reply_to_wins_over_explicit_ticket_number_in_text():
    """Even when the message ALSO happens to mention a different ticket
    number, in_reply_to -- the more explicit, un-inferred signal -- resolves
    first and the ticket-number lookup never runs."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "t-14", "ticket_number": "TKT-00014"}])
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+919876543213", "whatsapp",
        raw_text="re TKT-00099 -- it happens around 11PM",
        in_reply_to="wamid.ORIGINAL123", trace_id="tr-19b"))

    assert stub == {"id": "t-14", "ticketNumber": "TKT-00014"}
    db.list_tickets.assert_awaited_once_with("t1", originMessageId="wamid.ORIGINAL123", trace_id="tr-19b")


def test_ensure_ticket_stub_falls_back_when_in_reply_to_does_not_match_any_ticket():
    """An in_reply_to that matches nothing (e.g. the quoted message predates
    origin_message_id tracking) must not block resolution -- falls through
    to the next signal exactly like an unknown ticket-number reference does."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[[], [{"id": "t-1", "ticket_number": "TKT-00001"}]])
    db.create_ticket = AsyncMock()

    stub = _run(ensure_ticket_stub(
        db, "t1", "email:citizen@example.com", "email",
        subject="[Ticket TKT-00001]", in_reply_to="wamid.UNKNOWN", trace_id="tr-19c"))

    assert stub == {"id": "t-1", "ticketNumber": "TKT-00001"}
    assert db.list_tickets.await_count == 2
    db.list_tickets.assert_any_await("t1", originMessageId="wamid.UNKNOWN", trace_id="tr-19c")
    db.list_tickets.assert_any_await("t1", ticketNumber="TKT-00001", trace_id="tr-19c")


def test_unclear_verdict_records_the_suspicion_on_the_ticket_itself():
    """Feature 22: the citizen often never answers the duplicate question, so
    the flag cannot live only in conversation state (which expires in two
    hours) — an agent has to be able to see and settle it later."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[
        [{"id": "t-mdk", "ticket_number": "TKT-00042", "category": "water"}],
        [],
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-9"})
    db.get_messages = AsyncMock(
        return_value=[{"direction": "inbound", "content": "Water logging in Madambakkam"}])
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00043"})
    db.add_event = AsyncMock(return_value={})

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_UNCLEAR)):
        _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+919876543212", "whatsapp", raw_text="Water logging",
            channel_identity_type="phone", channel_identity_value="+919876543212", trace_id="tr-22d"))

    assert db.add_event.await_args.args[0] == "t-new"
    payload = db.add_event.await_args.args[1]
    assert payload["eventType"] == "ticket.possible_duplicate"
    assert payload["meta"]["duplicateOfId"] == "t-mdk"
    assert payload["meta"]["duplicateOfNumber"] == "TKT-00042"


def test_routing_survives_a_failed_suspicion_write():
    """Best-effort: the ticket is already created by then, and routing must
    not fail over an audit write."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(side_effect=[
        [{"id": "t-mdk", "ticket_number": "TKT-00042", "category": "water"}],
        [],
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-9"})
    db.get_messages = AsyncMock(
        return_value=[{"direction": "inbound", "content": "Water logging in Madambakkam"}])
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00043"})
    db.add_event = AsyncMock(side_effect=RuntimeError("db down"))

    with patch("app.tickets.intake.match_open_ticket", new=AsyncMock(return_value=_UNCLEAR)):
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+919876543212", "whatsapp", raw_text="Water logging",
            channel_identity_type="phone", channel_identity_value="+919876543212", trace_id="tr-22e"))

    assert stub["id"] == "t-new"
    assert stub["suspectedDuplicateOf"]["ticketNumber"] == "TKT-00042"
