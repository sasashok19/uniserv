"""Delivers `ai.reply.send` events (Feature 06 x 14) — the actual outbound
send that was missing: the conversation agent published identity requests,
follow-up questions, and confirmations to the event bus, but nothing ever
turned them into a real message back to the citizen.

Email is delivered via api-gateway's existing `EmailAdapter.sendReply`
(reused through its `/test-send` endpoint rather than duplicating SMTP
config here). WhatsApp has no outbound-send capability in this codebase yet
(Meta Business API outbound is Phase 2) — those are logged, not delivered.
"""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("ai-core")

IDENTITY_REQUEST_SUBJECT = "We need a bit more information about your complaint"
DEFAULT_SUBJECT = "Update on your message to UniServe"
TICKET_ACK_SUBJECT_TEMPLATE = "Your complaint has been registered — Ticket {ticket_number}"

# Feature 15: every reply that carries a ticket number must keep it in the
# subject — a citizen's reply preserves the subject line (as "Re: ..."),
# and that's what lets a follow-up email be matched back to THIS exact
# ticket instead of guessing by category (see app/tickets/intake.py).
DO_NOT_REMOVE_NOTE = (
    "\n\n---\nPlease do not remove or edit the ticket number in the subject "
    "line when replying — it's how we match your reply to this complaint."
)


def _subject_with_ticket(base_subject: str, ticket_number: Optional[str]) -> str:
    if not ticket_number:
        return base_subject
    return f"{base_subject} [Ticket {ticket_number}]"


async def send_email(
    to_address: str, subject: str, body: str, trace_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
) -> dict:
    """Deliver an email via api-gateway's `EmailAdapter.sendReply` (reused
    through its `/test-send` endpoint rather than duplicating SMTP config
    here). Shared by every citizen-facing email this service sends.

    `in_reply_to` — the ticket's origin inbound Message-ID (Feature 15), when
    known — sets In-Reply-To/References so this lands in the same chain in
    the citizen's mailbox instead of as a fresh, disconnected email.
    """
    # Never email RFC 2606 reserved/documentation domains (dev seed data uses
    # them). A real SMTP send to anon@example.com just generates a Gmail
    # bounce, which used to come back through IMAP and get filed as a new
    # "complaint" from mailer-daemon — a seed→bounce→ticket feedback loop.
    domain = (to_address or "").rsplit("@", 1)[-1].lower()
    if (domain in ("example.com", "example.org", "example.net", "example.edu")
            or domain.endswith((".example", ".invalid", ".test", ".localhost"))):
        logger.info("email skipped (reserved test domain): traceId=%s to=%s", trace_id, to_address)
        return {"delivered": False, "reason": "reserved test-domain recipient"}

    url = f"{settings.api_gateway_url.rstrip('/')}/api/v1/internal/adapters/email/test-send"
    headers = {"Content-Type": "application/json"}
    if trace_id:
        headers["X-Trace-Id"] = trace_id

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json={
                "to": to_address, "subject": subject, "body": body,
                "inReplyToMessageId": in_reply_to,
            })
        resp.raise_for_status()
        sent = bool(resp.json().get("sent"))
        if sent:
            logger.info("email delivered: traceId=%s to=%s subject=%s", trace_id, to_address, subject)
        else:
            logger.warning("email send reported false: traceId=%s to=%s", trace_id, to_address)
        return {"delivered": sent}
    except Exception as exc:  # noqa: BLE001 - report and let the caller decide on retry/DLQ
        logger.error("email delivery failed: traceId=%s to=%s error=%s", trace_id, to_address, exc)
        raise


async def deliver_reply(payload: dict, trace_id: Optional[str] = None) -> dict:
    channel = payload.get("channel")
    to_address = payload.get("channelIdentityValue")
    message_text = payload.get("messageText") or ""
    is_identity_request = bool(payload.get("isIdentityRequest"))
    ticket_number = payload.get("ticketNumber")
    origin_message_id = payload.get("originMessageId")

    if channel != "email":
        logger.info(
            "ai.reply.send recorded but not delivered: traceId=%s channel=%s "
            "(no outbound send wired for this channel yet)",
            trace_id, channel,
        )
        return {"delivered": False, "reason": f"no outbound send wired for channel '{channel}'"}

    if not to_address:
        logger.warning("ai.reply.send has no channelIdentityValue to reply to: traceId=%s", trace_id)
        return {"delivered": False, "reason": "no destination address"}

    base_subject = IDENTITY_REQUEST_SUBJECT if is_identity_request else DEFAULT_SUBJECT
    subject = _subject_with_ticket(base_subject, ticket_number)
    body = message_text + (DO_NOT_REMOVE_NOTE if ticket_number else "")
    return await send_email(to_address, subject, body, trace_id, in_reply_to=origin_message_id)


def _format_ticket_ack_body(ticket_number: str, category: Optional[str], status: str, is_duplicate: bool) -> str:
    lines = [
        "Thank you — your complaint has been recorded." if not is_duplicate
        else "Thank you — we've added your message to your existing complaint.",
        "",
        f"Ticket ID: {ticket_number}",
        f"Category: {category or 'Uncategorized'}",
        f"Status: {status or 'open'}",
        "",
        "We'll email you again whenever there's an update, and once this ticket "
        "is resolved or closed.",
    ]
    return "\n".join(lines) + DO_NOT_REMOVE_NOTE


async def send_ticket_ack_email(
    channel: str,
    to_address: Optional[str],
    ticket_number: Optional[str],
    category: Optional[str] = None,
    status: str = "open",
    is_duplicate: bool = False,
    trace_id: Optional[str] = None,
    origin_message_id: Optional[str] = None,
) -> dict:
    """Structured acknowledgment sent once a citizen's message becomes a
    tracked ticket (new or appended to an existing one) — carries the ticket
    ID so they have a reference for any follow-up (Feature 06 x 14)."""
    if channel != "email":
        logger.info("ticket ack recorded but not delivered: traceId=%s channel=%s ticketNumber=%s",
                     trace_id, channel, ticket_number)
        return {"delivered": False, "reason": f"no outbound send wired for channel '{channel}'"}

    if not to_address:
        logger.warning("ticket ack has no destination address: traceId=%s ticketNumber=%s", trace_id, ticket_number)
        return {"delivered": False, "reason": "no destination address"}

    if not ticket_number:
        logger.warning("ticket ack has no ticket number: traceId=%s", trace_id)
        return {"delivered": False, "reason": "no ticket number"}

    subject = TICKET_ACK_SUBJECT_TEMPLATE.format(ticket_number=ticket_number)
    body = _format_ticket_ack_body(ticket_number, category, status, is_duplicate)
    return await send_email(to_address, subject, body, trace_id, in_reply_to=origin_message_id)
