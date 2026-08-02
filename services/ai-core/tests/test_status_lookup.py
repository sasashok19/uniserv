"""Unit tests for the complaint status summary (Feature 17)."""

import asyncio
from unittest.mock import AsyncMock

from app.conversation.status_lookup import NO_COMPLAINTS_MESSAGE, summarize_recent_tickets


def _run(coro):
    return asyncio.run(coro)


def test_summarize_returns_no_complaints_message_when_identity_not_found():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value=None)

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert result == NO_COMPLAINTS_MESSAGE
    db.list_tickets.assert_not_called()


def test_summarize_returns_no_complaints_message_when_identity_has_no_tickets():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[])

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert result == NO_COMPLAINTS_MESSAGE


def test_summarize_uses_transition_note_as_last_action_when_present():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-1", "ticket_number": "TKT-00042", "category": "billing", "status": "resolved"},
    ])
    db.get_notes = AsyncMock(return_value=[
        {"content": "Escalated to billing team", "created_at": "2026-07-01T00:00:00Z"},
        {"content": "Refund processed, please allow 3-5 days", "created_at": "2026-07-05T00:00:00Z"},
    ])

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert "TKT-00042" in result
    assert "billing" in result
    assert "resolved" in result
    assert "Refund processed, please allow 3-5 days" in result
    assert "Escalated to billing team" not in result  # only the NEWEST note is shown
    db.get_messages.assert_not_called()  # notes existed — messages fallback never needed


def test_summarize_falls_back_to_last_outbound_message_when_no_notes():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-2", "ticket_number": "TKT-00043", "category": "technical", "status": "open"},
    ])
    db.get_notes = AsyncMock(return_value=[])
    db.get_messages = AsyncMock(return_value=[
        {"direction": "inbound", "content": "My meter is broken"},
        {"direction": "outbound", "content": "Thanks, a technician has been assigned."},
    ])

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert "Thanks, a technician has been assigned." in result
    assert "My meter is broken" not in result  # inbound messages aren't "actions taken"


def test_summarize_omits_last_update_when_ticket_has_no_notes_or_outbound_messages():
    """A brand-new ticket that hasn't been touched yet — no note/action to show."""
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-3", "ticket_number": "TKT-00044", "category": "other", "status": "open"},
    ])
    db.get_notes = AsyncMock(return_value=[])
    db.get_messages = AsyncMock(return_value=[])

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert "TKT-00044" in result
    assert "Last update" not in result


def test_summarize_lists_multiple_tickets_in_numbered_order():
    db = AsyncMock()
    db.find_by_email = AsyncMock(return_value={"master_id": "m-2"})
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-4", "ticket_number": "TKT-00050", "category": "billing", "status": "in_progress"},
        {"id": "t-5", "ticket_number": "TKT-00048", "category": "technical", "status": "resolved"},
    ])
    db.get_notes = AsyncMock(return_value=[])
    db.get_messages = AsyncMock(return_value=[])

    result = _run(summarize_recent_tickets(db, "t1", "email", "citizen@example.com"))

    assert "last 2 complaints" in result
    assert result.index("TKT-00050") < result.index("TKT-00048")  # order preserved from list_tickets
    assert "1. TKT-00050" in result
    assert "2. TKT-00048" in result


def test_summarize_passes_sort_and_limit_to_list_tickets():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[])

    _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210", limit=3, trace_id="tr-1"))

    db.list_tickets.assert_awaited_once_with(
        "t1", identityId="m-1", sortBy="createdAt", sortDir="desc", pageSize=3, trace_id="tr-1")


def test_summarize_a_single_ticket_uses_singular_header():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-6", "ticket_number": "TKT-00051", "category": "billing", "status": "open"},
    ])
    db.get_notes = AsyncMock(return_value=[])
    db.get_messages = AsyncMock(return_value=[])

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert result.startswith("Here is your complaint:")


def test_summarize_truncates_long_notes():
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-7", "ticket_number": "TKT-00052", "category": "billing", "status": "resolved"},
    ])
    db.get_notes = AsyncMock(return_value=[{"content": "x" * 300}])

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert "..." in result
    assert "x" * 300 not in result


def test_summarize_survives_notes_lookup_failure_for_one_ticket():
    """Best-effort: one ticket's history failing to load must not break the
    whole summary — that ticket just shows without a "last update" line."""
    db = AsyncMock()
    db.find_by_phone = AsyncMock(return_value={"master_id": "m-1"})
    db.list_tickets = AsyncMock(return_value=[
        {"id": "t-8", "ticket_number": "TKT-00053", "category": "billing", "status": "open"},
    ])
    db.get_notes = AsyncMock(side_effect=RuntimeError("db-writer timeout"))
    db.get_messages = AsyncMock(side_effect=RuntimeError("db-writer timeout"))

    result = _run(summarize_recent_tickets(db, "t1", "phone", "+919876543210"))

    assert "TKT-00053" in result
    assert "Last update" not in result
