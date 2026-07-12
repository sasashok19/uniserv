"""Unit tests for ticket stub lifecycle (Feature 06 x 12)."""

import asyncio
from unittest.mock import AsyncMock

from app.tickets.intake import ensure_ticket_stub, update_ticket_identity


def _run(coro):
    return asyncio.run(coro)


def test_ensure_ticket_stub_reuses_existing_ticket_for_thread():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "t-1", "ticket_number": "TKT-00001"}])
    db.create_ticket = AsyncMock()

    ticket_id = _run(ensure_ticket_stub(db, "t1", "email:citizen@example.com", "email", trace_id="tr-1"))

    assert ticket_id == "t-1"
    db.create_ticket.assert_not_called()
    db.list_tickets.assert_awaited_once_with("t1", threadId="email:citizen@example.com", trace_id="tr-1")


def test_ensure_ticket_stub_creates_bare_stub_when_none_exists():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])
    db.create_ticket = AsyncMock(return_value={"id": "t-2", "ticketNumber": "TKT-00002"})

    ticket_id = _run(ensure_ticket_stub(db, "t1", "email:new@example.com", "email", trace_id="tr-2"))

    assert ticket_id == "t-2"
    payload = db.create_ticket.await_args.args[0]
    assert payload["threadId"] == "email:new@example.com"
    assert payload["channelOrigin"] == "email"
    assert payload["identityStatus"] == "pending"
    assert payload["status"] == "open"


def test_update_ticket_identity_patches_identity_fields():
    db = AsyncMock()
    db.update_ticket = AsyncMock(return_value={})

    _run(update_ticket_identity(db, "t-1", "m-1", "confirmed", trace_id="tr-3"))

    db.update_ticket.assert_awaited_once_with(
        "t-1", {"identityId": "m-1", "identityStatus": "confirmed"}, trace_id="tr-3")
