"""Deduplication core logic (Feature 09), shared by the HTTP endpoint
(app/dedup/router.py) and the automatic complaint.ready → ticket pipeline
(app/tickets/service.py).

Phase 1: level-1 detection — same identity + same category with an open
ticket → append to existing; otherwise → new ticket.
"""

from typing import Optional

from app.identity.db_client import DbWriterClient

OPEN_STATUSES = "open,assigned,in_progress"


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
