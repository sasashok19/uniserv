"""Ticket lifecycle from the moment a message arrives (Feature 06 x 12).

Closes a gap in the original design: a ticket only existed once identity was
confirmed *and* enough complaint detail was gathered — a citizen who never
completed identity confirmation left no visible trace anywhere. Now a bare
stub is created on the very first message and updated in place (never
re-created) as the conversation progresses:

  arrival -> stub (identity_status=pending, no category)
  identity confirmed/anonymous -> same row, identityId + identityStatus set
  complaint.ready -> same row, category/priority/etc set (see tickets/service.py)

The thread->ticket lookup has to live in the database, not Valkey
conversation state: state expires in ~2 hours, but an unconfirmed thread may
sit for days before (or without ever) resolving identity.
"""

import logging
from typing import Optional

from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")


async def ensure_ticket_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str, trace_id: Optional[str] = None,
) -> str:
    """Find the ticket already tracking this thread, or create a bare stub."""
    existing = await db.list_tickets(tenant_id, threadId=thread_key, trace_id=trace_id)
    if existing:
        return existing[0]["id"]

    ticket = await db.create_ticket({
        "tenantId": tenant_id,
        "threadId": thread_key,
        "channelOrigin": channel,
        "identityStatus": "pending",
        "status": "open",
    }, trace_id=trace_id)
    logger.info("ticket stub created traceId=%s threadId=%s ticketId=%s ticketNumber=%s",
                trace_id, thread_key, ticket.get("id"), ticket.get("ticketNumber"))
    return ticket["id"]


async def update_ticket_identity(
    db: DbWriterClient, ticket_id: str, master_id: Optional[str], identity_status: str,
    trace_id: Optional[str] = None,
) -> None:
    """Reflect identity resolution onto the stub immediately — this is what
    moves a ticket out of the Unconfirmed queue as soon as identity confirms,
    independent of whether complaint details are ready yet."""
    await db.update_ticket(ticket_id, {
        "identityId": master_id,
        "identityStatus": identity_status,
    }, trace_id=trace_id)
    logger.info("ticket identity updated traceId=%s ticketId=%s identityStatus=%s masterId=%s",
                trace_id, ticket_id, identity_status, master_id)
