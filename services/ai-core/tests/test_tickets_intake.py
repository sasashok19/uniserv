"""Unit tests for ticket stub lifecycle (Feature 06 x 12 x 15)."""

import asyncio
from unittest.mock import AsyncMock

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
    db.list_tickets.assert_awaited_once_with("t1", threadId="email:citizen@example.com", trace_id="tr-1")


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


def test_extract_ticket_number_finds_reference_anywhere_in_subject():
    assert extract_ticket_number("Re: Billing issue [Ticket TKT-00042]") == "TKT-00042"
    assert extract_ticket_number("No reference here") is None
    assert extract_ticket_number(None) is None


def test_update_ticket_identity_patches_identity_fields():
    db = AsyncMock()
    db.update_ticket = AsyncMock(return_value={})

    _run(update_ticket_identity(db, "t-1", "m-1", "confirmed", trace_id="tr-3"))

    db.update_ticket.assert_awaited_once_with(
        "t-1", {"identityId": "m-1", "identityStatus": "confirmed"}, trace_id="tr-3")
