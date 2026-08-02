"""Complaint status summary (Feature 17): "what's the status of my complaint?"

Resolves the citizen's identity by their channel address (phone or email —
this is a READ-ONLY lookup, not an identity-CONFIRMING action, so it works
even for an unverified email address that's never been through the identity
gate) and summarises their most recent tickets — ticket number, category,
status, and the last note/action taken.

The summary is composed here, by code, from the raw ticket/notes/messages
data — never left to an LLM to paraphrase — so a citizen can't be told a
wrong status or a hallucinated note just because the model rephrased it.
"""

import logging
from typing import Optional

from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

DEFAULT_LIMIT = 5
NO_COMPLAINTS_MESSAGE = "We don't have any complaints on file for you yet."
_NOTE_SNIPPET_MAX = 200


async def _find_identity(
    db: DbWriterClient, tenant_id: str, identity_type: Optional[str], identity_value: Optional[str],
    trace_id: Optional[str] = None,
) -> Optional[dict]:
    if not identity_value:
        return None
    if identity_type == "phone":
        return await db.find_by_phone(tenant_id, identity_value, trace_id=trace_id)
    if identity_type == "email":
        return await db.find_by_email(tenant_id, identity_value, trace_id=trace_id)
    return None


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) > _NOTE_SNIPPET_MAX:
        return text[:_NOTE_SNIPPET_MAX].rstrip() + "..."
    return text


async def _last_action(db: DbWriterClient, ticket_id: str, trace_id: Optional[str] = None) -> Optional[str]:
    """The most recent internal/transition note (agent-facing "action
    taken"), falling back to the most recent outbound message when a ticket
    has no notes yet (e.g. still in the intake/unconfirmed stage). Best-effort:
    a lookup failure must never break the whole summary, just that one line."""
    try:
        notes = await db.get_notes(ticket_id, trace_id=trace_id)
        if notes:
            return notes[-1].get("content")
    except Exception:  # noqa: BLE001 - one ticket's history failing must not break the summary
        logger.warning("failed to fetch notes for status summary traceId=%s ticketId=%s", trace_id, ticket_id)

    try:
        messages = await db.get_messages(ticket_id, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - same as above
        logger.warning("failed to fetch messages for status summary traceId=%s ticketId=%s", trace_id, ticket_id)
        return None
    outbound = [m for m in messages if m.get("direction") == "outbound" and m.get("content")]
    return outbound[-1]["content"] if outbound else None


def _format_ticket_line(ticket: dict, last_action: Optional[str]) -> str:
    number = ticket.get("ticket_number") or ticket.get("ticketNumber") or "?"
    category = ticket.get("category") or "Uncategorized"
    status = ticket.get("status") or "open"
    line = f"{number} ({category}) — {status}"
    if last_action:
        line += f'. Last update: "{_truncate(last_action)}"'
    return line


async def summarize_recent_tickets(
    db: DbWriterClient, tenant_id: str, identity_type: Optional[str], identity_value: Optional[str],
    limit: int = DEFAULT_LIMIT, trace_id: Optional[str] = None,
) -> str:
    """A brief, factual summary of this identity's last `limit` complaints,
    most recent first — ticket number, category, status, and the last
    note/action — for a citizen asking about the status of their complaint(s).
    """
    identity = await _find_identity(db, tenant_id, identity_type, identity_value, trace_id=trace_id)
    if not identity or not identity.get("master_id"):
        return NO_COMPLAINTS_MESSAGE

    tickets = await db.list_tickets(
        tenant_id, identityId=identity["master_id"], sortBy="createdAt", sortDir="desc",
        pageSize=limit, trace_id=trace_id)
    if not tickets:
        return NO_COMPLAINTS_MESSAGE

    lines = []
    for ticket in tickets:
        last_action = await _last_action(db, ticket["id"], trace_id=trace_id)
        lines.append(_format_ticket_line(ticket, last_action))

    header = "Here is your complaint:" if len(lines) == 1 else f"Here are your last {len(lines)} complaints:"
    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1))
    logger.info("status summary composed traceId=%s masterId=%s ticketCount=%d",
                trace_id, identity["master_id"], len(lines))
    return f"{header}\n{numbered}"
