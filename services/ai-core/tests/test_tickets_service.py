"""Unit tests for complaint.ready -> ticket creation, incl. stub reuse (Feature 06 x 09 x 12)."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.tickets.service import create_ticket_from_complaint


def _run(coro):
    return asyncio.run(coro)


def _payload(**overrides):
    base = {
        "masterId": "m-1",
        "channel": "email",
        "identityStatus": "confirmed",
        "ticketId": "stub-1",
        "extractedFields": {"complaint_summary": "My meter is faulty", "category_hint": "product"},
    }
    base.update(overrides)
    return base


def test_create_ticket_from_complaint_updates_the_existing_stub_not_a_new_row():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])  # no dedup match
    db.update_ticket = AsyncMock(return_value={"ticket_number": "TKT-00010"})
    db.add_message = AsyncMock()

    result = _run(create_ticket_from_complaint(db, "t1", _payload(), trace_id="tr-1"))

    assert result["action"] == "new_ticket"
    assert result["ticketId"] == "stub-1"
    assert result["ticketNumber"] == "TKT-00010"
    assert result["status"] == "open"
    db.update_ticket.assert_awaited_once()
    ticket_id_arg, fields_arg = db.update_ticket.await_args.args
    assert ticket_id_arg == "stub-1"
    assert fields_arg["identityId"] == "m-1"
    assert fields_arg["category"]
    db.add_message.assert_awaited_once()
    assert db.add_message.await_args.args[0] == "stub-1"


def test_create_ticket_from_complaint_creates_fresh_when_no_stub_given():
    """Direct/test callers that bypass the live pipeline still work."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[])
    db.create_ticket = AsyncMock(return_value={"id": "t-99", "ticketNumber": "TKT-00099"})
    db.add_message = AsyncMock()

    payload = _payload(ticketId=None)
    result = _run(create_ticket_from_complaint(db, "t1", payload, trace_id="tr-2"))

    assert result["action"] == "new_ticket"
    assert result["ticketId"] == "t-99"
    assert result["ticketNumber"] == "TKT-00099"
    db.create_ticket.assert_awaited_once()


def test_create_ticket_from_complaint_links_stub_as_duplicate_when_dedup_matches():
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "existing-ticket", "category": "product"}])
    db.update_ticket = AsyncMock()
    db.add_message = AsyncMock()
    db.get_ticket = AsyncMock(return_value={
        "ticket_number": "TKT-00007", "category": "product", "status": "open",
    })

    result = _run(create_ticket_from_complaint(db, "t1", _payload(), trace_id="tr-3"))

    assert result["action"] == "append_to_existing"
    assert result["ticketId"] == "existing-ticket"
    assert result["ticketNumber"] == "TKT-00007"
    # Message goes to the CANONICAL ticket, not the stub.
    assert db.add_message.await_args.args[0] == "existing-ticket"
    # The stub itself is marked as a linked duplicate, not left stranded pending.
    db.update_ticket.assert_awaited_once()
    ticket_id_arg, fields_arg = db.update_ticket.await_args.args
    assert ticket_id_arg == "stub-1"
    assert fields_arg["isDuplicate"] == 1
    assert fields_arg["parentTicketId"] == "existing-ticket"
    assert fields_arg["status"] == "closed"
