"""The ticket's chief complaint (Feature 23) — one line saying what the
citizen actually wants, kept current as the conversation goes on.

Until now that answer existed nowhere queryable: it was implicit in the free
text of the ticket's first inbound message. The queue could show a ticket's
number, status, priority, category and channel — everything ABOUT the
complaint and nothing OF it — so triaging meant opening tickets one by one to
read the first message.

Two properties the field has to have, and both are why this is derived rather
than simply copied from the first message:

1. It comes from the message that TRIGGERED the ticket. Not from a category
   keyword match, not from an agent's note — from what the citizen wrote
   first, in their own terms.
2. It follows the conversation. A citizen's opening message is very often the
   least informative thing they will say ("no power"); the location, the
   meter number, the "it's the whole street, not just my house" all arrive in
   later replies. A chief complaint frozen at message one would be stale by
   the time an agent reads it.

Same best-effort contract as every other LLM-assisted decision here
(``app/classify/message_quality.py``, ``app/priority/llm_scorer.py``): a
plain chat completion, and any failure/unavailability falls back to a
deterministic condensation of the citizen's own text. A chief complaint is a
display and triage aid — it must never be able to block a ticket, a routing
decision, or the reply a citizen is waiting on.

Two rules that matter more than the wording:

- An intake-form answer is NOT a complaint. "Nithya",
  "nithya@gmail.com", "56784567" are answers to the questions we asked, and
  Feature 20 already has the deterministic test for that shape
  (``looks_like_intake_answer``). Without this guard the chief complaint of
  every WhatsApp ticket would end up being the citizen's own phone number,
  since intake answers are usually the second, third and fourth messages on
  a stub.
- A worse value never replaces a better one. Once the LLM has written a
  line, an LLM outage does not overwrite it with a raw truncation — the
  deterministic path only ever supplies the FIRST value.
"""

import json
import logging
import re
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from app.identity.db_client import DbWriterClient
from app.tickets.intake import looks_like_intake_answer

logger = logging.getLogger("ai-core")

_REQUEST_TIMEOUT_SECONDS = 10.0

# Long enough for "Water supply cut for three days in Anna Nagar 2nd Street",
# short enough to sit on one line of a queue row and a ticket header without
# the table having to give up a column to it.
MAX_CHARS = 140

_SYSTEM_PROMPT = (
    "You maintain the CHIEF COMPLAINT line on a public-utility service ticket: one short "
    f"sentence (at most {MAX_CHARS} characters) naming WHAT the citizen's problem is and, when "
    "they have said so, WHERE. It is the answer to \"what is this ticket about?\" that an agent "
    "reads before opening the conversation.\n"
    "Write it as a plain third-person statement: no greeting, no ticket number, no agent-facing "
    "commentary, no speculation about cause or fix, no trailing full stop. Keep the citizen's own "
    "words for the problem. Never add a detail they did not give.\n"
    "When an EXISTING chief complaint is supplied you are REVISING it using the citizen's latest "
    "message. Keep the original problem as the anchor and change the line only when the new "
    "message genuinely sharpens or corrects it — a location, a specific meter or bill, a duration, "
    "a second symptom, or a correction of something they said before. A message that adds nothing "
    "about the problem itself (\"any update?\", \"still not fixed\", \"thanks\", a name, an email "
    "address, a phone or customer number) leaves the line EXACTLY as it was.\n"
    "Respond with STRICT JSON only, no prose: "
    '{"chief_complaint": "<the line>", "changed": <true if you altered or wrote it>}'
)

# The intake block `app/tickets/service.py:_format_message_content` appends to a
# complaint. It is our own formatting, not the citizen's complaint, so the
# deterministic path cuts it off rather than condensing a "Mobile: ..." line.
_INTAKE_BLOCK_RE = re.compile(r"\n\s*-{3,}\s*\n|\n\s*Citizen-provided details:", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WHITESPACE_RE = re.compile(r"\s+")

# Below this a "sentence" is a fragment ("No power"), so the next one is pulled
# in too — an opening line of "Hi." must not become the chief complaint.
_MIN_USEFUL_CHARS = 20


def available() -> bool:
    """Whether the LLM path can be attempted — an API key only (a plain
    completion, not the Assistants gateway)."""
    return bool(settings.openai_api_key)


def condense(text: Optional[str]) -> Optional[str]:
    """Deterministic fallback: the citizen's own opening sentence(s), trimmed
    to one line. Used when the LLM is unavailable and the ticket has no chief
    complaint yet — a raw first sentence is a far better queue column than an
    empty cell, and it is the citizen's own wording either way."""
    body = _INTAKE_BLOCK_RE.split((text or "").strip(), maxsplit=1)[0]
    body = _WHITESPACE_RE.sub(" ", body).strip()
    if not body:
        return None

    picked = ""
    for sentence in _SENTENCE_SPLIT_RE.split(body):
        sentence = sentence.strip()
        if not sentence:
            continue
        picked = f"{picked} {sentence}".strip() if picked else sentence
        if len(picked) >= _MIN_USEFUL_CHARS:
            break
    if not picked:
        return None

    if len(picked) <= MAX_CHARS:
        return picked.rstrip(" .")
    # Truncate on a word boundary so the line never ends mid-word.
    cut = picked[:MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:.") or picked[:MAX_CHARS]
    return cut + "…"


async def _summarise(existing: Optional[str], new_text: str) -> Optional[str]:
    """One-line chief complaint from `new_text`, revising `existing` when there
    is one. Returns ``None`` when the model reports no change, or on any
    failure/unavailability (caller keeps whatever the ticket already had)."""
    if not available():
        return None
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS)
        user_message = (
            (f"EXISTING CHIEF COMPLAINT:\n{existing}\n\n" if existing else "")
            + f"CITIZEN'S {'LATEST' if existing else 'FIRST'} MESSAGE:\n{new_text}"
        )
        response = await client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        line = (parsed.get("chief_complaint") or "").strip()
        # An existing line plus "changed: false" is the model declining to
        # revise — the common case for a follow-up like "any update?", and the
        # whole reason it is asked for explicitly rather than diffed.
        if existing and not parsed.get("changed", True):
            logger.info("chief complaint unchanged by this message")
            return None
        if not line:
            return None
        return line[:MAX_CHARS].strip()
    except Exception as exc:  # noqa: BLE001 - best-effort, see module docstring
        logger.warning("chief-complaint summarisation failed, keeping the current value: %s", exc)
        return None


async def derive(
    existing: Optional[str], new_text: Optional[str], trace_id: Optional[str] = None,
) -> Optional[str]:
    """The chief complaint `new_text` implies, given whatever the ticket
    already has. Returns ``None`` to mean "keep `existing`" — including when
    the message is intake-form data, when the model says the line needs no
    revision, and when the LLM is unreachable and there is already a value.

    Touches no database, so a caller already writing the ticket row can fold
    the result into that write instead of issuing a second one (see
    ``app/tickets/service.py``); callers that hold no row use `refresh`.
    Never raises.
    """
    text = (new_text or "").strip()
    if not text:
        return None
    # Feature 20's structural test, reused: an answer to the intake form is
    # not a description of a problem, however short the message is.
    if looks_like_intake_answer(text):
        logger.info("chief complaint left as-is (message is intake-form data) traceId=%s", trace_id)
        return None

    current = (existing or "").strip() or None
    line = await _summarise(current, text)
    if line is None and current is None:
        # First value only: an LLM outage supplies the citizen's own opening
        # sentence rather than leaving the field empty. It is deliberately NOT
        # used to overwrite an existing line.
        line = condense(text)
    if not line or line == current:
        return None
    return line


async def refresh(
    db: DbWriterClient, ticket_id: str, new_text: Optional[str], trace_id: Optional[str] = None,
) -> Optional[str]:
    """`derive` against the ticket's stored value, writing the result back only
    when it actually changed. Returns the new line, or ``None`` when the
    ticket was left alone.

    Called from the places a citizen message reaches a ticket the caller isn't
    otherwise writing to — the conversation agent's inbound persistence, a
    confirmed duplicate merge, and a complaint appended to an existing ticket
    — which together are why a ticket has a chief complaint from its very
    first message and keeps up with every reply after it.

    Never raises: every caller is on the path of a reply the citizen is
    waiting for.
    """
    try:
        ticket = await db.get_ticket(ticket_id, trace_id=trace_id)
        existing = (ticket.get("chief_complaint") or "").strip() or None
        line = await derive(existing, new_text, trace_id=trace_id)
        if not line:
            return None
        await db.update_ticket(ticket_id, {"chiefComplaint": line}, trace_id=trace_id)
        logger.info("chief complaint %s traceId=%s ticketId=%s value=%r",
                    "updated" if existing else "set", trace_id, ticket_id, line)
        return line
    except Exception:  # noqa: BLE001 - best-effort, see module docstring
        logger.warning("failed to refresh chief complaint traceId=%s ticketId=%s", trace_id, ticket_id)
        return None
