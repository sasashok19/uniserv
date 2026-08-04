"""What is this inbound message FOR? (Feature 24)

The judgment that was missing, and the reason a citizen's "Yes it is" landed on
the wrong ticket. Everything routing could previously ask compared the new
message against *ticket complaint texts* (`is_same_topic`, `match_open_ticket`).
A reply like "Yes it is" contains no complaint content at all, so those
comparisons had nothing to work with and the fallbacks guessed.

The context that actually resolves it is **what we last asked them**. If we sent
"Is this resolved?" on TKT-00010 and the next thing they say is "Yes it is",
that is an answer to that question, on that ticket, whatever its status.

One call, three-way answer:

    {"answers_ticket": <1-based index|null>,
     "is_new_complaint": <bool>,
     "reason": "<short>"}

Deliberately ONE request rather than "does this answer us?" followed by "is this
a new complaint?". Two calls cost twice as much and can contradict each other —
both answering yes leaves the caller with a tie-break rule that is exactly the
kind of guess this module exists to remove.

Best-effort like every other LLM judgment here: any failure returns ``None``,
and the caller must then take the SAFE route — which for this judgment is to
ask the citizen (routing rung 5), never to guess a ticket and never to
silently create one.
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger("ai-core")

_REQUEST_TIMEOUT_SECONDS = 10.0

_SYSTEM_PROMPT = (
    "You route an inbound message at a public-utility complaint desk.\n"
    "You are given the OUTSTANDING QUESTIONS we have sent this citizen, numbered, each with the "
    "ticket it was asked on and that ticket's complaint. Then the citizen's NEW MESSAGE.\n"
    "\n"
    "Answer two things.\n"
    "\n"
    "1. answers_ticket: the number of the question this message replies to, or null.\n"
    "   - A short confirmation or denial (\"yes\", \"no\", \"yes it is\", \"it is resolved\", \"not "
    "yet\", \"still not working\", \"correct\") almost always answers the most recent question that "
    "such an answer would FIT. Match on what the question asked for, not on shared words.\n"
    "   - Pick the question this answer actually fits. If we asked \"Is this resolved?\" on one "
    "ticket and \"What is your meter number?\" on another, \"Yes it is\" answers the first and "
    "\"84402215\" answers the second.\n"
    "   - A ticket being resolved or closed does NOT disqualify it: we often ask whether something "
    "is fixed and the answer arrives after we closed it.\n"
    "   - null when the message plainly does not respond to any of them.\n"
    "\n"
    "2. is_new_complaint: true only if the message describes a problem the citizen wants fixed — "
    "it names something wrong (no power, water logging, meter not working, a wrong bill, a leak) in "
    "a way a human agent could act on. \n"
    "   - false for a bare acknowledgement, a courtesy (\"thanks\", \"ok\", \"you are correct\"), a "
    "greeting, a question about an existing complaint's status, or contact details on their own.\n"
    "   - A message can answer a question AND raise a new problem; set both.\n"
    "   - Brevity alone does not make it false: \"no power\" is a complaint.\n"
    "\n"
    "Respond with STRICT JSON only, no prose: "
    '{"answers_ticket": <number|null>, "is_new_complaint": <bool>, "reason": "<short reason>"}'
)


def available() -> bool:
    """Whether the judgment can be attempted — an API key only (a plain
    completion, not the Assistants gateway)."""
    return bool(settings.openai_api_key)


def _render(questions: list[dict]) -> str:
    lines = []
    for i, q in enumerate(questions):
        lines.append(
            f"{i + 1}. [{q.get('ticketNumber') or 'unnumbered'}] (ticket status: "
            f"{q.get('status') or 'unknown'})\n"
            f"   WE ASKED: {(q.get('question') or '').strip() or '(nothing recorded)'}\n"
            f"   THEIR COMPLAINT: {(q.get('complaint') or '').strip() or '(none recorded)'}"
        )
    return "\n\n".join(lines)


async def assess_inbound(
    questions: list[dict], new_text: str, trace_id: Optional[str] = None,
) -> Optional[dict]:
    """Route `new_text` against our outstanding `questions`.

    `questions` is ``[{"ticketNumber", "status", "question", "complaint"}]`` in
    the order to present them — newest question first, so "the most recent
    question this could answer" is a position the model can reason about.

    Returns ``{"index": Optional[int], "is_new_complaint": bool, "reason": str}``
    where `index` is a position in `questions`, or ``None`` on any
    failure/unavailability.

    Called with an EMPTY `questions` list too: with nothing outstanding the only
    question left is "is this a new complaint?", and asking it here keeps one
    prompt responsible for that decision on every path.
    """
    if not available():
        return None
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS)
        user_message = (
            ("OUTSTANDING QUESTIONS WE SENT THIS CITIZEN:\n" + _render(questions)
             if questions else
             "OUTSTANDING QUESTIONS WE SENT THIS CITIZEN:\n(none — we are not waiting on anything)")
            + f"\n\nNEW MESSAGE:\n{new_text}"
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

        index = parsed.get("answers_ticket")
        # The model answers in 1-based positions from the listing above. Anything
        # outside it — a hallucinated number, a ticket id, a bool — means "none",
        # never an arbitrary ticket.
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= len(questions):
            index = None
        else:
            index -= 1

        result = {
            "index": index,
            "is_new_complaint": bool(parsed.get("is_new_complaint", False)),
            "reason": parsed.get("reason") or "",
        }
        logger.info("inbound intent assessed traceId=%s answersIndex=%s newComplaint=%s reason=%s",
                    trace_id, result["index"], result["is_new_complaint"], result["reason"])
        return result
    except Exception as exc:  # noqa: BLE001 - best-effort; caller asks the citizen instead
        logger.warning("inbound intent assessment failed traceId=%s, will ask the citizen: %s",
                       trace_id, exc)
        return None
