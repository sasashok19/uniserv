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
    db.get_ticket = AsyncMock(return_value={"id": "stub-1", "category": None})  # fresh stub
    db.list_tickets = AsyncMock(return_value=[])
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
    # A fresh stub never triggers category-based cross-ticket dedup.
    db.list_tickets.assert_not_called()


def test_create_ticket_from_complaint_persists_service_id_when_present():
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"id": "stub-1", "category": None})
    db.list_tickets = AsyncMock(return_value=[])
    db.update_ticket = AsyncMock(return_value={"ticket_number": "TKT-00011"})
    db.add_message = AsyncMock()

    payload = _payload(extractedFields={
        "complaint_summary": "My meter is faulty",
        "category_hint": "product",
        "intake": {"serviceId": "SVC-4521", "mobile": "+919876543210", "name": "Jane"},
    })
    _run(create_ticket_from_complaint(db, "t1", payload, trace_id="tr-4"))

    fields_arg = db.update_ticket.await_args.args[1]
    assert fields_arg["serviceId"] == "SVC-4521"


def test_create_ticket_from_complaint_treats_second_message_on_same_stub_as_continuation():
    """A second complaint.ready on the SAME thread/stub (already categorized)
    is a continuation, not a fresh complaint — no cross-ticket dedup involved."""
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={
        "id": "stub-1", "category": "product", "ticket_number": "TKT-00007", "status": "open",
    })
    db.update_ticket = AsyncMock()
    db.add_message = AsyncMock()

    result = _run(create_ticket_from_complaint(db, "t1", _payload(), trace_id="tr-5"))

    assert result["action"] == "append_to_existing"
    assert result["ticketId"] == "stub-1"
    assert result["ticketNumber"] == "TKT-00007"
    assert db.add_message.await_args.args[0] == "stub-1"
    # Same ticket, not a different one — never marked as a linked duplicate.
    db.update_ticket.assert_not_called()
    db.list_tickets.assert_not_called()


def test_create_ticket_from_complaint_never_cross_merges_a_different_new_complaint():
    """Regression test: two different stub tickets for the same citizen,
    same category, must never be merged just because a category-based
    lookup would find the other one — this was the reported bug."""
    db = AsyncMock()
    db.get_ticket = AsyncMock(return_value={"id": "stub-2", "category": None})  # brand-new stub
    db.update_ticket = AsyncMock(return_value={"ticket_number": "TKT-00020"})
    db.add_message = AsyncMock()

    payload = _payload(ticketId="stub-2", extractedFields={
        "complaint_summary": "My water pressure is too low", "category_hint": "outage",
    })
    result = _run(create_ticket_from_complaint(db, "t1", payload, trace_id="tr-6"))

    assert result["action"] == "new_ticket"
    assert result["ticketId"] == "stub-2"
    db.add_message.assert_awaited_once()
    assert db.add_message.await_args.args[0] == "stub-2"
    db.list_tickets.assert_not_called()


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


def test_create_ticket_from_complaint_no_stub_fallback_still_dedups_by_category():
    """Only reachable for callers that bypass the live pipeline entirely
    (no stub at all) — the coarser identity+category heuristic remains as
    a fallback there, since there's no thread/subject signal to use instead."""
    db = AsyncMock()
    db.list_tickets = AsyncMock(return_value=[{"id": "existing-ticket", "category": "product"}])
    db.add_message = AsyncMock()
    db.get_ticket = AsyncMock(return_value={
        "ticket_number": "TKT-00007", "category": "product", "status": "open",
    })

    result = _run(create_ticket_from_complaint(db, "t1", _payload(ticketId=None), trace_id="tr-3"))

    assert result["action"] == "append_to_existing"
    assert result["ticketId"] == "existing-ticket"
    assert result["ticketNumber"] == "TKT-00007"
    assert db.add_message.await_args.args[0] == "existing-ticket"
