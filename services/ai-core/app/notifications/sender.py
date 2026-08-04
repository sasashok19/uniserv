"""Delivers `ai.reply.send` events (Feature 06 x 14) — the actual outbound
send that was missing: the conversation agent published identity requests,
follow-up questions, and confirmations to the event bus, but nothing ever
turned them into a real message back to the citizen.

Email is delivered via api-gateway's existing `EmailAdapter.sendReply`
(reused through its `/test-send` endpoint rather than duplicating SMTP
config here). WhatsApp is delivered via api-gateway's `WhatsAppAdapter.sendReply`
(Meta Graph API, through its `/send` endpoint) the same way — this service
never talks to Meta or an SMTP server directly, only to api-gateway.

Note (Meta's 24-hour customer service window): a WhatsApp free-form text
message can only be sent within 24h of the citizen's last inbound message;
outside that window the send fails (Graph API error), since sending a
pre-approved template message instead is not implemented. Identity requests
and follow-ups happen inside an active conversation so this rarely bites,
but a resolve/close status update days later could land outside the window
— see docs/02b_ADAPTER_WHATSAPP.md.
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


def _error_body_snippet(exc: Exception) -> Optional[str]:
    """api-gateway's own error response body, when the failure is an HTTP
    error status — httpx's default exception message ("Server error '500...'
    for url ...") never includes it, so without this the REAL cause (e.g.
    Resend's 403 detail) only ever showed up in api-gateway's logs, not
    ai-core's, forcing a cross-service log hunt for every delivery failure."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return response.text[:500]


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
        async with httpx.AsyncClient(timeout=settings.email_send_timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json={
                "to": to_address, "subject": subject, "body": body,
                "inReplyToMessageId": in_reply_to,
            })
        resp.raise_for_status()
        body_json = resp.json()
        sent = bool(body_json.get("sent"))
        if sent:
            logger.info("email delivered: traceId=%s to=%s subject=%s", trace_id, to_address, subject)
        else:
            logger.warning("email send reported false: traceId=%s to=%s", trace_id, to_address)
        # Feature 24: the Message-ID the gateway put on this mail. Returned so
        # the caller can stamp it onto the persisted message — that is what makes
        # the citizen's reply to it routable back to this exact ticket.
        return {"delivered": sent, "channelMessageId": body_json.get("channelMessageId")}
    except Exception as exc:  # noqa: BLE001 - report and let the caller decide on retry/DLQ
        logger.error("email delivery failed: traceId=%s to=%s error=%s body=%s",
                      trace_id, to_address, exc, _error_body_snippet(exc))
        raise


async def send_whatsapp(
    to_phone: str, body: str, trace_id: Optional[str] = None,
    context_message_id: Optional[str] = None,
) -> dict:
    """Deliver a WhatsApp text message via api-gateway's `WhatsAppAdapter.sendReply`
    (reused through its `/send` endpoint rather than talking to Meta's Graph API
    directly from this service).

    `context_message_id` — the citizen's inbound wamid (Feature 15 parity with
    email's `in_reply_to`), when known — makes the reply render as a quoted
    reply-to in WhatsApp instead of a fresh, disconnected message.
    """
    url = f"{settings.api_gateway_url.rstrip('/')}/api/v1/internal/adapters/whatsapp/send"
    headers = {"Content-Type": "application/json"}
    if trace_id:
        headers["X-Trace-Id"] = trace_id

    try:
        async with httpx.AsyncClient(timeout=settings.whatsapp_send_timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json={
                "to": to_phone, "body": body, "contextMessageId": context_message_id,
            })
        resp.raise_for_status()
        body_json = resp.json()
        sent = bool(body_json.get("sent"))
        if sent:
            logger.info("whatsapp delivered: traceId=%s to=%s", trace_id, to_phone)
        else:
            logger.warning("whatsapp send reported false: traceId=%s to=%s", trace_id, to_phone)
        # Feature 24: Meta's wamid for this message — see send_email above.
        return {"delivered": sent, "channelMessageId": body_json.get("channelMessageId")}
    except Exception as exc:  # noqa: BLE001 - report and let the caller decide on retry/DLQ
        logger.error("whatsapp delivery failed: traceId=%s to=%s error=%s body=%s",
                      trace_id, to_phone, exc, _error_body_snippet(exc))
        raise


async def deliver_reply(payload: dict, trace_id: Optional[str] = None) -> dict:
    channel = payload.get("channel")
    to_address = payload.get("channelIdentityValue")
    message_text = payload.get("messageText") or ""
    is_identity_request = bool(payload.get("isIdentityRequest"))
    ticket_number = payload.get("ticketNumber")
    origin_message_id = payload.get("originMessageId")

    if not to_address:
        logger.warning("ai.reply.send has no channelIdentityValue to reply to: traceId=%s", trace_id)
        return {"delivered": False, "reason": "no destination address"}

    if channel == "email":
        base_subject = IDENTITY_REQUEST_SUBJECT if is_identity_request else DEFAULT_SUBJECT
        subject = _subject_with_ticket(base_subject, ticket_number)
        body = message_text + (DO_NOT_REMOVE_NOTE if ticket_number else "")
        return await send_email(to_address, subject, body, trace_id, in_reply_to=origin_message_id)

    if channel == "whatsapp":
        # No subject/DO_NOT_REMOVE_NOTE: WhatsApp doesn't have a subject line
        # and dedup/threading there is by phone identity, not a preserved
        # ticket-number tag (see docs/09... subject-line threading is email-only).
        return await send_whatsapp(to_address, message_text, trace_id, context_message_id=origin_message_id)

    logger.info(
        "ai.reply.send recorded but not delivered: traceId=%s channel=%s "
        "(no outbound send wired for this channel yet)",
        trace_id, channel,
    )
    return {"delivered": False, "reason": f"no outbound send wired for channel '{channel}'"}


def _format_ticket_ack_body(
    ticket_number: str, category: Optional[str], status: str, is_duplicate: bool,
    channel: str,
) -> str:
    lines = [
        "Thank you — your complaint has been recorded." if not is_duplicate
        else "Thank you — we've added your message to your existing complaint.",
        "",
        f"Ticket ID: {ticket_number}",
        f"Category: {category or 'Uncategorized'}",
        f"Status: {status or 'open'}",
        "",
        "We'll notify you again whenever there's an update, and once this ticket "
        "is resolved or closed.",
    ]
    body = "\n".join(lines)
    # DO_NOT_REMOVE_NOTE is about preserving the ticket number in an email
    # SUBJECT line — WhatsApp has no subject, and dedup there is by phone
    # identity instead, so the note would be actively misleading.
    return body + DO_NOT_REMOVE_NOTE if channel == "email" else body


async def send_ticket_ack(
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
    if not to_address:
        logger.warning("ticket ack has no destination address: traceId=%s ticketNumber=%s", trace_id, ticket_number)
        return {"delivered": False, "reason": "no destination address"}

    if not ticket_number:
        logger.warning("ticket ack has no ticket number: traceId=%s", trace_id)
        return {"delivered": False, "reason": "no ticket number"}

    body = _format_ticket_ack_body(ticket_number, category, status, is_duplicate, channel)

    if channel == "email":
        subject = TICKET_ACK_SUBJECT_TEMPLATE.format(ticket_number=ticket_number)
        return await send_email(to_address, subject, body, trace_id, in_reply_to=origin_message_id)

    if channel == "whatsapp":
        return await send_whatsapp(to_address, body, trace_id, context_message_id=origin_message_id)

    logger.info("ticket ack recorded but not delivered: traceId=%s channel=%s ticketNumber=%s",
                 trace_id, channel, ticket_number)
    return {"delivered": False, "reason": f"no outbound send wired for channel '{channel}'"}
