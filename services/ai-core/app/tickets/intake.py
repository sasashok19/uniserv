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

Feature 15: a reply's subject line is a far more reliable signal than
thread/category matching for "is this the SAME complaint, continued" — an
email client always keeps the subject (as "Re: ...") when a citizen replies,
so once a ticket's number is embedded in every outbound subject, an inbound
subject that echoes it back unambiguously identifies which ticket this
message belongs to. A citizen starting a brand-new email (no ticket number
in the subject) is, by definition, a different complaint and must never be
folded into an old ticket just because it happens to land in the same
category — see the removed category-based dedup in tickets/service.py.
"""

import logging
import re
from typing import Optional

from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

TICKET_NUMBER_RE = re.compile(r"TKT-\d{4,}")


def extract_ticket_number(subject: Optional[str]) -> Optional[str]:
    """Pull a ticket number (e.g. "TKT-00042") out of an email subject line."""
    if not subject:
        return None
    match = TICKET_NUMBER_RE.search(subject)
    return match.group(0) if match else None


async def ensure_ticket_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    subject: Optional[str] = None, trace_id: Optional[str] = None,
) -> dict:
    """Find the ticket this message belongs to, or create a bare stub.

    Subject-line ticket number (when present) takes priority over thread
    matching — it is a citizen-visible, explicit reference rather than an
    inferred one, and is what lets a reply to an old ticket resolve to that
    exact ticket even if the underlying transport thread/message-id
    tracking (In-Reply-To headers, etc.) fails or the citizen re-quotes an
    old message in a new one.
    """
    referenced = extract_ticket_number(subject)
    if referenced:
        matches = await db.list_tickets(tenant_id, ticketNumber=referenced, trace_id=trace_id)
        if matches:
            logger.info("ticket resolved via subject reference traceId=%s ticketNumber=%s ticketId=%s",
                        trace_id, referenced, matches[0]["id"])
            return {"id": matches[0]["id"], "ticketNumber": matches[0].get("ticket_number")}
        logger.warning("subject referenced unknown ticket traceId=%s ticketNumber=%s — treating as new",
                        trace_id, referenced)

    existing = await db.list_tickets(tenant_id, threadId=thread_key, trace_id=trace_id)
    if existing:
        return {"id": existing[0]["id"], "ticketNumber": existing[0].get("ticket_number")}

    ticket = await db.create_ticket({
        "tenantId": tenant_id,
        "threadId": thread_key,
        "channelOrigin": channel,
        "identityStatus": "pending",
        "status": "open",
    }, trace_id=trace_id)
    logger.info("ticket stub created traceId=%s threadId=%s ticketId=%s ticketNumber=%s",
                trace_id, thread_key, ticket.get("id"), ticket.get("ticketNumber"))
    return {"id": ticket["id"], "ticketNumber": ticket.get("ticketNumber")}


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
