"""Unit tests for ticket stub lifecycle (Feature 06 x 12 x 15)."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.dedup.service import OPEN_STATUSES
from app.tickets.intake import ensure_ticket_stub, extract_ticket_number, update_ticket_identity


def _run(coro):
    return asyncio.run(coro)


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
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-power", "ticket_number": "TKT-00090", "category": "outage"},
    ])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-ashok"})
    db.get_messages = AsyncMock(return_value=[
        {"direction": "inbound", "content": "No power"},
    ])
    db.create_ticket = AsyncMock(return_value={"id": "t-new", "ticketNumber": "TKT-00091"})

    with patch("app.tickets.intake.is_same_topic", new=AsyncMock(return_value=False)) as same_topic:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939012727", "whatsapp",
            raw_text="Put not closed", channel_identity_type="phone",
            channel_identity_value="+918939012727", trace_id="tr-18a"))

    assert stub == {"id": "t-new", "ticketNumber": "TKT-00091"}
    same_topic.assert_awaited_once_with("No power", "outage", "Put not closed")


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

    with patch("app.tickets.intake.is_same_topic", new=AsyncMock(return_value=True)):
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

    with patch("app.tickets.intake.is_same_topic", new=AsyncMock(return_value=None)):
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

    with patch("app.tickets.intake.is_same_topic", new=AsyncMock()) as same_topic:
        stub = _run(ensure_ticket_stub(
            db, "t1", "whatsapp:+918939012727", "whatsapp",
            raw_text="Put not closed", channel_identity_type="phone",
            channel_identity_value="+918939012727", trace_id="tr-18d"))

    assert stub == {"id": "t-power", "ticketNumber": "TKT-00090"}
    same_topic.assert_not_called()


def test_ensure_ticket_stub_whatsapp_creates_new_when_multiple_open_tickets():
    """Genuinely ambiguous (2+ open tickets, no explicit reference) — the
    safe default is a NEW ticket, never a silent guess-merge. Resolved
    entirely via identity — the threadId fallback is never consulted, since
    that would just pick one of the very tickets just judged ambiguous."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(
        return_value=[{"id": "t-open-1", "ticket_number": "TKT-00061"}, {"id": "t-open-2", "ticket_number": "TKT-00062"}])
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-3"})
    db.create_ticket = AsyncMock(return_value={"id": "t-new-2", "ticketNumber": "TKT-00070"})

    stub = _run(ensure_ticket_stub(
        db, "t1", "whatsapp:+919876543212", "whatsapp",
        raw_text="A completely different issue", channel_identity_type="phone",
        channel_identity_value="+919876543212", trace_id="tr-8"))

    assert stub == {"id": "t-new-2", "ticketNumber": "TKT-00070"}
    db.list_tickets.assert_awaited_once()


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


def test_ensure_ticket_stub_email_channel_never_uses_identity_fallback():
    """Regression guard: email already has its own (better) subject-based
    mechanism — the identity+open-count fallback is WhatsApp-specific and
    must not kick in for email even when a channel identity value is passed."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])
    db.find_by_email = AsyncMock()
    db.create_ticket = AsyncMock(return_value={"id": "t-email-new", "ticketNumber": "TKT-00080"})

    stub = _run(ensure_ticket_stub(
        db, "t1", "email:msg-abc", "email",
        raw_text="My bill is wrong", channel_identity_type="email",
        channel_identity_value="citizen@example.com", trace_id="tr-10"))

    assert stub == {"id": "t-email-new", "ticketNumber": "TKT-00080"}
    db.find_by_email.assert_not_called()


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


def test_update_ticket_identity_patches_identity_fields():
    db = AsyncMock()
    db.update_ticket = AsyncMock(return_value={})

    _run(update_ticket_identity(db, "t-1", "m-1", "confirmed", trace_id="tr-3"))

    db.update_ticket.assert_awaited_once_with(
        "t-1", {"identityId": "m-1", "identityStatus": "confirmed"}, trace_id="tr-3")
