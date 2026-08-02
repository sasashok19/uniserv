"""Message quality assessment (Feature 18): is an inbound message coherent
enough to act on, and does it plausibly continue an identity's one existing
open ticket or look like a different complaint?

Both are plain chat-completion calls (same pattern as
``app/priority/llm_scorer.py``) — not the Assistants gateway, no thread/run
state, just a single stateless judgment. Best-effort throughout: any
error, timeout, missing key, or unparseable response returns ``None``, and
every caller MUST treat that as "assume the safe default" (coherent /
same-topic) — a false negative here (rejecting or splitting a genuine
complaint because the LLM hiccupped) is far worse than a false positive,
since a citizen whose real complaint gets silently dropped has no other
way to complain.

Live-testing motivation for both functions:
- A citizen wrote "Ashok, miscemail19@gmail.com" then, separately, "Put not
  closed" — a keyword classifier can't tell "pit"/"put" apart from
  anything, so a coarse category-match check can't catch this; only real
  content understanding can (see ``is_same_topic``).
- A garbled or clearly-nonsensical message should not silently become a
  ticket — but brevity alone ("no power") is NOT incoherence; the bar is
  specifically for text a human agent genuinely could not act on
  (see ``assess_coherence``).
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger("ai-core")

_REQUEST_TIMEOUT_SECONDS = 10.0

_COHERENCE_SYSTEM_PROMPT = (
    "You judge whether a short citizen message is a coherent complaint/feedback "
    "description, or gibberish/nonsensical noise that a human agent could not "
    "act on. Brief, terse, or vague messages (e.g. \"no power\", \"still broken\", "
    "\"any update?\") ARE coherent — brevity is not the test. Judge it NOT "
    "coherent only when the text itself doesn't form an understandable "
    "statement: random characters, keyboard mashing, or a word that looks like "
    "a likely typo changing the meaning of an otherwise-parseable sentence. "
    "Respond with STRICT JSON only, no prose: "
    '{"coherent": <bool>, "reason": "<short reason, or null if coherent>"}.'
)

_SAME_TOPIC_SYSTEM_PROMPT = (
    "You judge whether a citizen's NEW message plausibly continues their "
    "EXISTING open complaint, or describes a different, unrelated issue. "
    "Vague follow-ups with no new subject matter (\"any update?\", \"still not "
    "fixed\", \"please help\") DO continue the existing complaint. A message "
    "naming a different subject, location, or problem — even if terse or "
    "using different wording — does NOT. Respond with STRICT JSON only, no "
    'prose: {"same_topic": <bool>, "reason": "<short reason>"}.'
)


def available() -> bool:
    """Whether either assessment can be attempted at all — only an API key is
    required (a plain completion, not the Assistants gateway)."""
    return bool(settings.openai_api_key)


async def assess_coherence(text: str) -> Optional[dict]:
    """Is `text` clear enough to act on as a complaint?

    Returns ``{"coherent": bool, "reason": Optional[str]}``, or ``None`` on
    any failure/unavailability. An empty/blank message is always incoherent
    (no LLM call needed for that).
    """
    stripped = (text or "").strip()
    if not stripped:
        return {"coherent": False, "reason": "empty message"}
    if not available():
        return None
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _COHERENCE_SYSTEM_PROMPT},
                {"role": "user", "content": stripped},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        coherent = bool(parsed.get("coherent", True))
        reason = parsed.get("reason")
        logger.info("message coherence assessed coherent=%s reason=%s", coherent, reason)
        return {"coherent": coherent, "reason": reason}
    except Exception as exc:  # noqa: BLE001 - best-effort; caller assumes coherent
        logger.warning("coherence assessment failed, assuming coherent: %s", exc)
        return None


async def is_same_topic(existing_text: str, existing_category: Optional[str], new_text: str) -> Optional[bool]:
    """Does `new_text` plausibly continue the complaint described by
    `existing_text` (the identity's one other open ticket), or does it look
    like a different, unrelated complaint?

    Returns ``True``/``False``, or ``None`` on any failure/unavailability —
    callers fall back to the coarser default (treat as same topic, i.e.
    append) rather than creating a new-ticket-creation gap.
    """
    if not available():
        return None
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS)
        user_message = (
            f"EXISTING COMPLAINT (category: {existing_category or 'uncategorised'}):\n{existing_text}\n\n"
            f"NEW MESSAGE:\n{new_text}"
        )
        response = await client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SAME_TOPIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        same_topic = bool(parsed.get("same_topic", True))
        logger.info("same-topic assessed sameTopic=%s reason=%s", same_topic, parsed.get("reason"))
        return same_topic
    except Exception as exc:  # noqa: BLE001 - best-effort; caller assumes same topic
        logger.warning("same-topic assessment failed, assuming same topic: %s", exc)
        return None
