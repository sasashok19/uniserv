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


# ---------------------------------------------------------------------------
# Feature 18: even with the reorder fix, "exactly one open ticket" was still
# an UNCONDITIONAL append — count alone can't tell a genuine follow-up apart
# from an unrelated second complaint, and a keyword classifier gives no
# signal either way for text like "Put not closed" (matches no category).
# These test the real content-level check that closes that gap.
# ---------------------------------------------------------------------------


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


