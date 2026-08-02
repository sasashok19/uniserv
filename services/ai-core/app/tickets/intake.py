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

Feature 17: WhatsApp has no subject line, so it never had an equivalent of
the above — its thread key (`whatsapp:<phone>`) is the SAME for every
message that number ever sends, and the old threadId lookup below applied
no status filter at all. That meant a citizen whose ticket had already been
resolved, texting weeks later about something completely unrelated, got
silently appended to the old, resolved ticket rather than starting a new
one. Fixes, all channel-agnostic in principle:
- An explicit `TKT-XXXXX` reference now resolves regardless of channel —
  checked in the raw message body, not just an email subject, so a citizen
  on ANY channel who mentions a ticket number gets routed to it exactly
  (this is also what a citizen naturally does when asked to disambiguate
  between multiple open tickets, below).
- The threadId fallback now requires the ticket still be OPEN — an
  accidental thread-key collision (WhatsApp) must never resurrect a closed
  ticket, whereas a citizen-typed reference still can (that's a deliberate
  citizen action, e.g. reopening).
- For a channel with no subject line at all (WhatsApp today), resolution
  now tries identity + open-ticket count BEFORE the threadId match, not
  after: zero open tickets -> new; exactly one -> append (matches the
  identity+category dedup `check_duplicate` already does for the no-stub
  case); two or more -> still create a new ticket rather than guessing
  which one this continues (a wrong silent merge is worse than an extra
  ticket an agent can merge by hand). The threadId match is now reached
  ONLY when identity hasn't linked to any ticket yet (still a safety net
  for that narrow window) — it used to run FIRST, which meant it always
  won as long as a single ticket for that phone number was open, silently
  reusing it for a genuinely unrelated new complaint (reported live: a
  second, different complaint got appended as a note onto an existing
  "No power" ticket) — the exact "too coarse a signal" failure mode
  category-based dedup had for email, just recreated one layer deeper.
  A full "which of your N open complaints is this" back-and-forth is not
  implemented yet (see README's "Subject-line ticket threading & dedup"
  section).
"""

import logging
import re
from typing import Optional

from app.dedup.service import OPEN_STATUSES
from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

TICKET_NUMBER_RE = re.compile(r"TKT-\d{4,}")


def extract_ticket_number(text: Optional[str]) -> Optional[str]:
    """Pull a ticket number (e.g. "TKT-00042") out of a subject line or
    message body — either way, an explicit citizen-visible reference."""
    if not text:
        return None
    match = TICKET_NUMBER_RE.search(text)
    return match.group(0) if match else None


async def _find_identity_for_channel(
    db: DbWriterClient, tenant_id: str, identity_type: Optional[str], identity_value: Optional[str],
    trace_id: Optional[str] = None,
) -> Optional[dict]:
    """Best-effort identity lookup by the channel's own address — used only
    for ROUTING (which open ticket, if any, this message continues), not for
    identity confirmation (that's the conversation agent's job)."""
    if not identity_value:
        return None
    if identity_type == "phone":
        return await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
    if identity_type == "email":
        return await db.find_by_email(tenant_id, identity_value, trace_id=trace_id)
    return None


async def ensure_ticket_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    subject: Optional[str] = None, raw_text: Optional[str] = None,
    channel_identity_type: Optional[str] = None, channel_identity_value: Optional[str] = None,
    origin_message_id: Optional[str] = None, trace_id: Optional[str] = None,
) -> dict:
    """Find the ticket this message belongs to, or create a bare stub.

    An explicit ticket-number reference (subject or message body) takes
    priority over everything else — it is a citizen-visible, explicit
    reference rather than an inferred one, and is what lets a reply to an
    old ticket resolve to that exact ticket even if the underlying
    transport thread/message-id tracking (In-Reply-To headers, etc.) fails
    or the citizen re-quotes an old message in a new one. `thread_key`
    itself is unique per email when there's no real In-Reply-To (see
    `ConversationAgent._thread_key`), so the threadId lookup is a
    perfectly good PRIMARY signal for email; for WhatsApp (a stable
    per-phone key, not a per-conversation one) it's only a safety-net
    FALLBACK for the narrow window before identity has linked to a ticket
    at all — see module docstring for why it can't be the primary signal
    there.
    """
    referenced = extract_ticket_number(subject) or extract_ticket_number(raw_text)
    if referenced:
        matches = await db.list_tickets(tenant_id, ticketNumber=referenced, trace_id=trace_id)
        if matches:
            logger.info("ticket resolved via explicit reference traceId=%s ticketNumber=%s ticketId=%s",
                        trace_id, referenced, matches[0]["id"])
            return {"id": matches[0]["id"], "ticketNumber": matches[0].get("ticket_number")}
        logger.warning("message referenced unknown ticket traceId=%s ticketNumber=%s — treating as new",
                        trace_id, referenced)

    if channel != "email" and channel_identity_value:
        identity = await _find_identity_for_channel(
            db, tenant_id, channel_identity_type, channel_identity_value, trace_id=trace_id)
        if identity and identity.get("master_id"):
            open_tickets = await db.list_tickets(
                tenant_id, identityId=identity["master_id"], status=OPEN_STATUSES,
                sortBy="createdAt", sortDir="desc", trace_id=trace_id)
            if len(open_tickets) == 1:
                logger.info("ticket resolved via identity's sole open ticket traceId=%s ticketId=%s",
                            trace_id, open_tickets[0]["id"])
                return {"id": open_tickets[0]["id"], "ticketNumber": open_tickets[0].get("ticket_number")}
            if len(open_tickets) > 1:
                logger.info(
                    "identity has %d open tickets and no explicit reference — creating a new ticket "
                    "rather than guessing which one this continues traceId=%s masterId=%s",
                    len(open_tickets), trace_id, identity["master_id"],
                )
                return await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)
            # Exactly zero open tickets linked to this identity — fall
            # through to the thread-key check below (safety net for a
            # ticket that hasn't been linked to the identity yet, e.g.
            # still on its very first turn).

    existing = await db.list_tickets(tenant_id, threadId=thread_key, status=OPEN_STATUSES, trace_id=trace_id)
    if existing:
        return {"id": existing[0]["id"], "ticketNumber": existing[0].get("ticket_number")}

    return await _create_stub(db, tenant_id, thread_key, channel, origin_message_id, trace_id)


async def _create_stub(
    db: DbWriterClient, tenant_id: str, thread_key: str, channel: str,
    origin_message_id: Optional[str], trace_id: Optional[str],
) -> dict:
    ticket = await db.create_ticket({
        "tenantId": tenant_id,
        "threadId": thread_key,
        "channelOrigin": channel,
        "identityStatus": "pending",
        "status": "open",
        "originMessageId": origin_message_id,
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
