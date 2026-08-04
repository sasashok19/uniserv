"""Deduplication core logic (Feature 09), shared by the HTTP endpoint
(app/dedup/router.py) and the automatic complaint.ready → ticket pipeline
(app/tickets/service.py).

Phase 1: level-1 detection — same identity + same category with an open
ticket → append to existing; otherwise → new ticket.
"""

from typing import Optional

from app.identity.db_client import DbWriterClient

# A complaint still being worked. `pending_customer` BELONGS here and its
# absence was a bug (Feature 24): that status means "we asked the citizen
# something and are waiting", so a ticket in it is the single most likely
# destination for the next inbound message — and it was invisible to routing,
# which meant every answer to a parked follow-up spawned a fresh ticket.
OPEN_STATUSES = "open,assigned,in_progress,pending_customer,reopened"

# Every status an inbound message may still be ATTRIBUTED to (Feature 24).
# Wider than the above on purpose: an agent asks "Is this resolved?" and marks
# the ticket resolved, the citizen answers "Yes it is" — that answer belongs on
# the resolved ticket, and excluding terminal statuses from routing is what sent
# it to an unrelated one. Attribution is not the same question as "is this
# ticket open"; nothing here reopens or otherwise changes a ticket's status.
ADDRESSABLE_STATUSES = OPEN_STATUSES + ",resolved,closed,cancelled"

# Statuses where appending an inbound message deserves an audit note, because
# the ticket is finished and nobody is necessarily watching it any more.
TERMINAL_STATUSES = frozenset({"resolved", "closed", "cancelled"})


async def check_duplicate(db: DbWriterClient, tenant_id: str, master_id: str, category: str,
                          trace_id: Optional[str] = None) -> dict:
    existing = await db.list_tickets(
        tenant_id, identityId=master_id, category=category, status=OPEN_STATUSES, trace_id=trace_id)
    if existing:
        ticket = existing[0]
        return {
            "action": "append_to_existing",
            "existingTicketId": ticket.get("id"),
            "confidence": "high",
            "reason": "Same identity, same category, open ticket exists",
        }
    return {"action": "new_ticket", "confidence": "high"}
