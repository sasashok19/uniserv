"""Ask before creating a duplicate (Feature 26).

Before this, an ambiguous repeat complaint — an open "Power Cut in Madambakkam"
and a new bare "Power cut" — created a second ticket immediately and *then*
asked the citizen about it. Two rows existed from the first message, the queue
showed both, and the merge only happened if the citizen bothered to answer.

Now the ambiguous case creates nothing. The question is asked first, the
citizen's own words are held here, and the ticket is created (or not) once they
answer. The cost of being wrong is one extra question instead of a duplicate row
somebody has to reconcile.

**Exactly one round.** If the answer is still ambiguous the ticket IS created,
carrying the Feature 22 ``suspectedDuplicateOf`` flag as before. A citizen who
cannot be understood twice must not be trapped in a loop that never files their
complaint — at that point a flagged ticket an agent can settle is the better
failure.

State lives in Valkey under ``dupconfirm:{tenant}:{thread_key}``, which is
channel-agnostic on purpose: the duplicate problem is not a WhatsApp problem,
and an email thread gets the same treatment.
"""

import json
import logging
import re
from typing import Any, Optional

from app.classify.message_quality import match_open_ticket
from app.events.client import get_valkey
from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

# Long enough for a citizen to reply after stepping away, short enough that a
# forgotten question cannot silently swallow a complaint they send days later.
PENDING_TTL_HOURS = 24

_AFFIRMATIVE_RE = re.compile(
    r"^(y|ya|yes|yeah|yep|yup|correct|right|same|thats it|that's it|it is|yes it is|"
    r"same one|same issue|same complaint|aama|ama|sari)\b[\s.!]*$",
    re.IGNORECASE)
_NEGATIVE_RE = re.compile(
    r"^(n|no|nope|nah|different|not the same|another one|new one|its different|it's different|"
    r"illai|illa)\b[\s.!]*$",
    re.IGNORECASE)


def _key(tenant_id: str, thread_key: str) -> str:
    return f"dupconfirm:{tenant_id}:{thread_key}"


async def save_pending(tenant_id: str, thread_key: str, pending: dict) -> None:
    try:
        await get_valkey().set(
            _key(tenant_id, thread_key), json.dumps(pending), ex=PENDING_TTL_HOURS * 3600)
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.warning("failed to save pending duplicate confirmation: %s", exc)


async def load_pending(tenant_id: str, thread_key: str) -> Optional[dict]:
    try:
        raw = await get_valkey().get(_key(tenant_id, thread_key))
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.warning("failed to load pending duplicate confirmation: %s", exc)
        return None
    if not raw:
        return None
    try:
        pending = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return pending if isinstance(pending, dict) else None


async def clear_pending(tenant_id: str, thread_key: str) -> None:
    try:
        await get_valkey().delete(_key(tenant_id, thread_key))
    except Exception as exc:  # noqa: BLE001 - best-effort
        logger.warning("failed to clear pending duplicate confirmation: %s", exc)


def classify_answer(text: Optional[str]) -> Optional[bool]:
    """A bare yes/no, if that is unambiguously what this is.

    Deterministic and checked before any LLM call: "yes" needs no model, and a
    citizen who answered plainly should not have their answer re-interpreted.
    Returns None for anything substantive ("Madambakkam", "no, this one is in
    Velachery") so the caller re-judges it with the full context — a message
    that both answers and adds detail is worth more than its first word.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    if _AFFIRMATIVE_RE.match(stripped):
        return True
    if _NEGATIVE_RE.match(stripped):
        return False
    return None


async def resolve(
    db: DbWriterClient, tenant_id: str, thread_key: str, pending: dict,
    answer_text: Optional[str], trace_id: Optional[str] = None,
) -> dict:
    """Settle a pending duplicate question with the citizen's answer.

    Returns one of:

    * ``{"outcome": "same", "ticketId", "ticketNumber"}`` — the citizen's message
      belongs on the existing ticket. Nothing new is created.
    * ``{"outcome": "different", "text"}`` — a genuinely new complaint. ``text``
      is the ORIGINAL complaint plus the detail they just added, so the ticket
      that gets created describes the whole thing rather than only the answer.
    * ``{"outcome": "unclear", "text", "duplicateOf"}`` — still ambiguous after
      one round. The caller creates the ticket and flags the suspicion.
    """
    original = pending.get("text") or ""
    duplicate_of = pending.get("duplicateOf") or {}
    combined = f"{original}\n{answer_text}".strip() if answer_text else original

    decided = classify_answer(answer_text)
    if decided is True:
        logger.info("duplicate confirmed by the citizen traceId=%s ticketId=%s",
                    trace_id, duplicate_of.get("id"))
        return {"outcome": "same", "ticketId": duplicate_of.get("id"),
                "ticketNumber": duplicate_of.get("ticketNumber")}
    if decided is False:
        logger.info("duplicate denied by the citizen traceId=%s", trace_id)
        return {"outcome": "different", "text": combined}

    # A substantive answer ("Madambakkam"). Re-judge the WHOLE complaint —
    # original plus the detail that was missing — against the same candidate.
    # Re-judging the answer alone would compare "Madambakkam" to a power-cut
    # complaint and conclude, correctly but uselessly, that they differ.
    candidate_text = duplicate_of.get("summary") or ""
    match = await match_open_ticket(
        [{"ticketNumber": duplicate_of.get("ticketNumber"), "text": candidate_text,
          "category": duplicate_of.get("category")}],
        combined)

    if match is None:
        # The judgment was unavailable, which is a network condition rather than
        # a decision. Create the ticket and flag it: an agent settling a flagged
        # pair is recoverable, a complaint dropped because OpenAI was down is not.
        logger.info("duplicate re-judgment unavailable traceId=%s — creating and flagging", trace_id)
        return {"outcome": "unclear", "text": combined, "duplicateOf": duplicate_of}

    verdict = match.get("verdict")
    if verdict == "same" and match.get("index") is not None:
        logger.info("duplicate resolved as the same complaint traceId=%s ticketId=%s reason=%s",
                    trace_id, duplicate_of.get("id"), match.get("reason"))
        return {"outcome": "same", "ticketId": duplicate_of.get("id"),
                "ticketNumber": duplicate_of.get("ticketNumber")}
    if verdict == "different":
        logger.info("duplicate resolved as a different complaint traceId=%s reason=%s",
                    trace_id, match.get("reason"))
        return {"outcome": "different", "text": combined}

    logger.info("duplicate still unclear after one round traceId=%s — creating and flagging", trace_id)
    return {"outcome": "unclear", "text": combined, "duplicateOf": duplicate_of}


async def attach_to_existing(
    db: DbWriterClient, tenant_id: str, ticket_id: str, channel: str, text: str,
    trace_id: Optional[str] = None,
) -> bool:
    """Put the citizen's words on the ticket they confirmed, and audit the merge.

    This is what "merged appropriately" means when no second ticket was ever
    created: there is nothing to mark ``is_duplicate`` and nothing to close, so
    the merge is the message landing on the right ticket plus the event that
    records why. The agent-facing path (``POST /tickets/{id}/duplicate``) still
    handles the case where two rows really do exist.
    """
    if not ticket_id or not (text or "").strip():
        return False
    try:
        await db.add_message(ticket_id, {
            "tenantId": tenant_id,
            "channel": channel,
            "direction": "inbound",
            "authorType": "user",
            "content": text,
        }, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - reported so the caller does not acknowledge a lost message
        logger.exception("failed to attach a confirmed duplicate to %s traceId=%s", ticket_id, trace_id)
        return False
    try:
        await db.add_event(ticket_id, {
            "eventType": "ticket.duplicate_prevented",
            "actorType": "ai",
            "meta": {"reason": "citizen confirmed this continues the existing complaint"},
        }, trace_id=trace_id)
    except Exception:  # noqa: BLE001 - the message is saved; its audit line is best-effort
        logger.warning("failed to record duplicate_prevented event for %s traceId=%s", ticket_id, trace_id)
    return True


def build_question(content: Optional[dict], duplicate_of: dict, question: str) -> str:
    """The message that asks the citizen to disambiguate.

    Names the existing complaint explicitly — "we already have a ticket for a
    power cut in Madambakkam" — because a citizen cannot answer a question about
    a record they cannot see. Falls back to a plain composition when no tenant
    menu copy is available (e.g. email).
    """
    number = duplicate_of.get("ticketNumber") or ""
    summary = (duplicate_of.get("summary") or "").strip()
    if len(summary) > 160:
        summary = summary[:160].rstrip() + "..."
    if content:
        from app.conversation import menu_content
        return menu_content.render(
            content, "duplicateAsk", ticket=number, existing=summary, question=question)
    prefix = f"Before I raise a new ticket — we already have ticket {number} open" if number \
        else "Before I raise a new ticket — we already have a complaint open"
    if summary:
        prefix += f' for "{summary}"'
    return f"{prefix}. {question}"


def as_pending(text: str, chosen: dict, summary: str, question: str) -> dict[str, Any]:
    """The state to hold while waiting for the citizen's answer."""
    return {
        "text": text,
        "question": question,
        "duplicateOf": {
            "id": chosen.get("id"),
            "ticketNumber": chosen.get("ticket_number") or chosen.get("ticketNumber"),
            "category": chosen.get("category"),
            "summary": summary,
        },
    }
