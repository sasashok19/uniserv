"""PII scrub / rehydrate (Feature 07).

PHASE_1 note: the spec calls for Presidio, but Presidio needs a spaCy model that
is not shipped in this image. This implementation uses regex + a light "name is"
heuristic to detect PERSON, PHONE_NUMBER, EMAIL_ADDRESS, IN_AADHAAR and IN_PAN —
the same entity labels and token format. The token map is stored in Valkey
(TTL = PII_TOKEN_TTL_MINUTES) and used to rehydrate the LLM's response.
"""

import json
import re

from app.config import settings
from app.events.client import get_valkey

# "My name is Rajesh Kumar" / "I am Rajesh Kumar" -> capture the name (group 1).
_PERSON_RE = re.compile(
    r"(?:name is|i am|i'm|this is|myself)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})")

# label, token-prefix, regex (whole-match replaced). Order does not matter; matches
# are resolved by position after collection.
_SIMPLE_DETECTORS = [
    ("EMAIL_ADDRESS", "EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("IN_PAN", "IN_PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("IN_AADHAAR", "IN_AADHAAR", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("PHONE_NUMBER", "PHONE", re.compile(r"(?:\+\d{1,3}[\s-]?)?\d{5}[\s-]?\d{5}\b")),
]


def _token_key(trace_id: str) -> str:
    return f"pii:{trace_id}"


def scrub_text(text: str) -> tuple[str, list[str], dict]:
    """Return (scrubbed_text, entities_found, token_map)."""
    matches = []  # (start, end, label, prefix, original)

    for m in _PERSON_RE.finditer(text):
        matches.append((m.start(1), m.end(1), "PERSON", "PERSON", m.group(1)))
    for label, prefix, rx in _SIMPLE_DETECTORS:
        for m in rx.finditer(text):
            matches.append((m.start(), m.end(), label, prefix, m.group(0)))

    # Resolve overlaps: earliest start wins, then longest.
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    chosen = []
    occupied = []
    for mt in matches:
        s, e = mt[0], mt[1]
        if any(not (e <= os or s >= oe) for os, oe in occupied):
            continue
        chosen.append(mt)
        occupied.append((s, e))
    chosen.sort(key=lambda x: x[0])

    counters: dict[str, int] = {}
    token_map: dict[str, str] = {}
    entities: list[str] = []
    out = []
    last = 0
    for s, e, label, prefix, original in chosen:
        counters[prefix] = counters.get(prefix, 0) + 1
        token = f"[{prefix}_{counters[prefix]}]"
        token_map[token] = original
        if label not in entities:
            entities.append(label)
        out.append(text[last:s])
        out.append(token)
        last = e
    out.append(text[last:])
    return "".join(out), entities, token_map


async def scrub(text: str, trace_id: str) -> dict:
    if not settings.pii_scrubber_enabled:
        return {"scrubbed": text, "entitiesFound": [], "tokenCount": 0}

    scrubbed, entities, token_map = scrub_text(text)
    if token_map:
        await get_valkey().set(
            _token_key(trace_id), json.dumps(token_map),
            ex=settings.pii_token_ttl_minutes * 60)
    return {"scrubbed": scrubbed, "entitiesFound": entities, "tokenCount": len(token_map)}


async def rehydrate(text: str, trace_id: str) -> str:
    raw = await get_valkey().get(_token_key(trace_id))
    if not raw:
        return text
    token_map = json.loads(raw)
    for token, original in token_map.items():
        text = text.replace(token, original)
    return text
