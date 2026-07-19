"""Rubric-based priority scoring via an LLM (Feature 03 priority rubric).

When a tenant configures a free-text ``priorityRubric`` AND an OpenAI key is
available, priority is scored by asking the model to apply that rubric to the
complaint instead of the deterministic weighted engine in
``app/priority/engine.py``. This is a plain chat completion (unlike the
Assistants gateway in ``app/conversation/openai_gateway.py``) so it needs only
an API key — no assistant id.

Every entry point is best-effort: any error, timeout, or unparseable response
returns ``None`` so the caller falls back to the deterministic engine and
ticket creation is never broken by an LLM problem.
"""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from app.priority.engine import _clamp, label_for

logger = logging.getLogger("ai-core")

# Keep the LLM off the critical path: a slow model must never stall ticket
# creation — we fall back to the deterministic engine instead.
_REQUEST_TIMEOUT_SECONDS = 15.0

_SYSTEM_PROMPT = (
    "You are a triage assistant that assigns a priority to a citizen complaint by "
    "applying the tenant's priority rubric EXACTLY as written. Read the rubric, then "
    "score the complaint. Respond with STRICT JSON only, no prose, in the form "
    '{"score": <number 0-10>, "label": "<critical|high|medium|low>"}.'
)


def rubric_available() -> bool:
    """Whether rubric-based scoring can be attempted at all. Only an API key is
    required (this is a plain completion, not the Assistants gateway which also
    needs an assistant id)."""
    return bool(settings.openai_api_key)


async def score_with_rubric(
    rubric: str, complaint_text: str, category: str, channel: str,
) -> Optional[dict]:
    """Score priority by asking the LLM to apply ``rubric`` to the complaint.

    Returns ``{"score": <float 0-10>, "label": "<critical|high|medium|low>"}``
    or ``None`` on any error/timeout so the caller can fall back to the
    deterministic engine. The score is clamped to [0, 10]; a missing or invalid
    label is derived from ``engine.label_for``.
    """
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS)
        user_message = (
            f"PRIORITY RUBRIC:\n{rubric}\n\n"
            f"COMPLAINT:\n{complaint_text}\n\n"
            f"category: {category}\n"
            f"channel: {channel}"
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
        content = response.choices[0].message.content or ""
        parsed = json.loads(content)

        # Score is authoritative; clamp defensively (models occasionally emit
        # out-of-range or string numbers).
        score_value = round(_clamp(float(parsed["score"])), 1)

        label = parsed.get("label")
        if label not in ("critical", "high", "medium", "low"):
            label = label_for(score_value)

        logger.info("priority scored via rubric score=%s label=%s category=%s channel=%s",
                    score_value, label, category, channel)
        return {"score": score_value, "label": label}
    except Exception as exc:  # noqa: BLE001 - best-effort; caller falls back to the engine
        logger.warning("rubric scoring failed, falling back to deterministic engine: %s", exc)
        return None
