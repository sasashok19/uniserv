"""Turns a `complaint.ready` event into a real ticket (Feature 09 x 10 x 04).

Closes the gap where `ConversationAgent` published `complaint.ready` but
nothing consumed it: this runs the same dedup check the standalone
`/api/v1/internal/deduplicate` endpoint exposes, scores priority, and either
creates a new ticket or appends the message to an existing open one.
"""

import logging
from typing import Optional

from app.classify.classifier import classify
from app.dedup.service import check_duplicate
from app.identity.db_client import DbWriterClient
from app.priority.engine import ScoreRequest, score

logger = logging.getLogger("ai-core")


def _format_message_content(complaint_summary: str, intake: Optional[dict]) -> str:
    """Prepend the citizen-provided intake fields (Feature 06 intake form),
    when present, to the complaint text so agents see the full context."""
    if not intake:
        return complaint_summary
    details = []
    if intake.get("serviceId"):
        details.append(f"Service/Customer ID: {intake['serviceId']}")
    if intake.get("mobile"):
        details.append(f"Mobile: {intake['mobile']}")
    if intake.get("name"):
        details.append(f"Name: {intake['name']}")
    if intake.get("pinCode"):
        details.append(f"Area Pin Code: {intake['pinCode']}")
    if not details:
        return complaint_summary
    return complaint_summary + "\n\n---\nCitizen-provided details:\n" + "\n".join(details)


async def create_ticket_from_complaint(
    db: DbWriterClient, tenant_id: str, payload: dict, trace_id: Optional[str] = None,
) -> dict:
    master_id = payload.get("masterId")
    channel = payload.get("channel") or "unknown"
    identity_status = payload.get("identityStatus", "pending")
    # The stub already created on arrival (Feature 12) — reused here rather
    # than creating a second row for the same thread. Falls back to creating
    # fresh only for callers that bypass the live pipeline (direct tests).
    stub_ticket_id = payload.get("ticketId")
    extracted = payload.get("extractedFields") or {}
    complaint_summary = (extracted.get("complaint_summary") or "").strip()
    category_hint = extracted.get("category_hint", "other")
    message_content = _format_message_content(complaint_summary, extracted.get("intake"))

    classification = classify(complaint_summary)
    category = classification.get("category") or category_hint
    sentiment = classification.get("sentimentScore", 0.0)

    existing_stub: Optional[dict] = None
    if stub_ticket_id:
        # Feature 12/15: this thread already has its own ticket — resolved
        # either by thread tracking or (for email) a subject-line ticket
        # reference (see app/tickets/intake.py). Whether THIS is a
        # continuation or the ticket's first-ever complaint.ready is decided
        # by the ticket's own state (does it already have a category?), not
        # by matching against OTHER tickets — category-based cross-ticket
        # dedup was removed because it risked folding an unrelated NEW
        # complaint from the same citizen into an old open ticket just
        # because it happened to classify into the same category.
        existing_stub = await db.get_ticket(stub_ticket_id, trace_id=trace_id)
        if existing_stub.get("category"):
            dedup_result = {"action": "append_to_existing", "existingTicketId": stub_ticket_id,
                            "confidence": "high", "reason": "continuing this ticket's own thread"}
        else:
            dedup_result = {"action": "new_ticket", "confidence": "high", "reason": "first complaint on this stub"}
    elif master_id:
        # No stub for this thread (only possible for callers that bypass the
        # live pipeline, e.g. direct/test calls) — fall back to the coarser
        # same-identity/same-category heuristic.
        dedup_result = await check_duplicate(db, tenant_id, master_id, category, trace_id=trace_id)
    else:
        # No resolved identity (e.g. anonymous resolution failed upstream) —
        # nothing to dedup against; always file as a new ticket.
        dedup_result = {"action": "new_ticket", "confidence": "low", "reason": "no resolved identity"}

    if dedup_result["action"] == "append_to_existing":
        existing_ticket_id = dedup_result["existingTicketId"]
        await db.add_message(existing_ticket_id, {
            "tenantId": tenant_id,
            "channel": channel,
            "direction": "inbound",
            "authorType": "user",
            "content": message_content,
        }, trace_id=trace_id)
        # This thread's own stub is a duplicate of a DIFFERENT ticket — link
        # it rather than leaving it stranded with identityStatus=pending
        # forever (which would otherwise never leave the Unconfirmed queue).
        if stub_ticket_id and stub_ticket_id != existing_ticket_id:
            await db.update_ticket(stub_ticket_id, {
                "identityId": master_id,
                "identityStatus": identity_status,
                "isDuplicate": 1,
                "parentTicketId": existing_ticket_id,
                "status": "closed",
            }, trace_id=trace_id)
        existing_ticket = existing_stub if existing_stub is not None and existing_stub.get("id") == existing_ticket_id \
            else await db.get_ticket(existing_ticket_id, trace_id=trace_id)
        logger.info("complaint appended to existing ticket traceId=%s ticketId=%s category=%s",
                    trace_id, existing_ticket_id, category)
        return {
            "action": "append_to_existing",
            "ticketId": existing_ticket_id,
            "ticketNumber": existing_ticket.get("ticket_number"),
            "category": existing_ticket.get("category") or category,
            "status": existing_ticket.get("status") or "open",
        }

    priority = score(ScoreRequest(
        tenantId=tenant_id, sentimentScore=sentiment, categoryLabel=category, channel=channel,
    ))
    intake = extracted.get("intake") or {}
    ticket_fields = {
        "identityId": master_id,
        "identityStatus": identity_status,
        "identitySource": channel,
        "category": category,
        "subcategory": classification.get("subcategory"),
        "priorityScore": priority["score"],
        "priorityLabel": priority["label"],
        "sentimentScore": sentiment,
    }
    if intake.get("serviceId"):
        ticket_fields["serviceId"] = intake["serviceId"]

    if stub_ticket_id:
        ticket = await db.update_ticket(stub_ticket_id, ticket_fields, trace_id=trace_id)
        ticket_id = stub_ticket_id
        ticket_number = ticket.get("ticket_number")  # PATCH returns the raw snake_case row
    else:
        ticket = await db.create_ticket({
            **ticket_fields, "tenantId": tenant_id, "status": "open", "channelOrigin": channel,
        }, trace_id=trace_id)
        ticket_id = ticket["id"]
        ticket_number = ticket.get("ticketNumber")  # POST returns a remapped camelCase shape

    await db.add_message(ticket_id, {
        "tenantId": tenant_id,
        "channel": channel,
        "direction": "inbound",
        "authorType": "user",
        "content": message_content,
    }, trace_id=trace_id)

    logger.info("ticket created traceId=%s ticketNumber=%s ticketId=%s category=%s priority=%s",
                trace_id, ticket_number, ticket_id, category, priority["label"])
    return {
        "action": "new_ticket",
        "ticketId": ticket_id,
        "ticketNumber": ticket_number,
        "category": category,
        "status": "open",
    }
