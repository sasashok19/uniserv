"""Rule-based complaint classifier (Feature 08).

PHASE_1: when no LLM is available the pipeline falls back to this deterministic
keyword classifier (the doc's `rule_based_classification` fallback). It returns
the same shape the LLM prompt would produce.
"""

import re
from typing import Optional

from pydantic import BaseModel

# category -> (keywords, {subcategory: keywords})
CATEGORY_KEYWORDS: dict[str, dict] = {
    "billing": {
        "keywords": ["bill", "billing", "amount", "charge", "payment", "invoice", "refund", "overcharge"],
        "sub": {
            "incorrect_amount": ["double", "wrong", "high", "incorrect", "extra", "more"],
            "payment_not_reflected": ["not reflected", "not updated", "paid", "deducted"],
        },
    },
    "outage": {
        "keywords": ["power", "outage", "electricity", "supply", "voltage", "cut", "blackout", "current"],
        "sub": {
            "power_cut": ["cut", "no power", "no supply", "blackout"],
            "low_voltage": ["low voltage", "fluctuat", "flicker"],
        },
    },
    "service": {
        "keywords": ["service", "staff", "rude", "response", "agent", "behaviour", "behavior", "support"],
        "sub": {},
    },
    "technical": {
        "keywords": ["app", "website", "login", "error", "portal", "otp", "password", "crash"],
        "sub": {},
    },
    "product": {
        "keywords": ["meter", "device", "connection", "installation", "product"],
        "sub": {},
    },
}

POSITIVE_WORDS = ["thank", "thanks", "great", "good", "excellent", "appreciate", "happy", "resolved"]
NEGATIVE_WORDS = ["double", "wrong", "worst", "angry", "terrible", "not", "never", "again",
                  "second time", "still", "unacceptable", "delay", "no response", "frustrat"]
QUERY_WORDS = ["how", "when", "what", "where", "can i", "could you", "is it possible", "?"]
COMPLIMENT_WORDS = ["excellent", "appreciate", "great job", "well done", "thank you"]


class ClassifyRequest(BaseModel):
    tenantId: str
    text: str
    traceId: Optional[str] = None


def classify(text: str) -> dict:
    lower = (text or "").lower()

    # Category scoring by keyword hits.
    best_category = "other"
    best_hits: list[str] = []
    best_count = 0
    best_sub = None
    for category, spec in CATEGORY_KEYWORDS.items():
        hits = [kw for kw in spec["keywords"] if kw in lower]
        if len(hits) > best_count:
            best_count = len(hits)
            best_category = category
            best_hits = hits
            best_sub = _subcategory(lower, spec["sub"])

    # Confidence: scales with keyword hits; low/other when nothing matches.
    if best_count == 0:
        category = "other"
        confidence = 0.31
        subcategory = None
    else:
        category = best_category
        confidence = round(min(0.55 + 0.18 * best_count, 0.97), 2)
        subcategory = best_sub

    intent = _intent(lower)
    sentiment = _sentiment(lower)
    keywords = _keywords(text, best_hits)

    result = {
        "intent": intent,
        "category": category,
        "confidence": confidence,
        "sentimentScore": sentiment,
        "keywords": keywords,
    }
    if subcategory:
        result["subcategory"] = subcategory
    return result


def _subcategory(lower: str, sub_map: dict) -> Optional[str]:
    for sub, kws in sub_map.items():
        if any(kw in lower for kw in kws):
            return sub
    return None


def _intent(lower: str) -> str:
    if any(w in lower for w in COMPLIMENT_WORDS):
        return "compliment"
    if any(w in lower for w in POSITIVE_WORDS) and not any(w in lower for w in ["not", "wrong", "double"]):
        return "feedback"
    if lower.strip().endswith("?") or any(w in lower for w in ["how do", "when will", "can i", "could you"]):
        return "query"
    return "complaint"


def _sentiment(lower: str) -> float:
    neg = sum(1 for w in NEGATIVE_WORDS if w in lower)
    pos = sum(1 for w in POSITIVE_WORDS if w in lower)
    raw = pos - neg
    # Map to [-1, 1] with mild saturation.
    score = max(-1.0, min(1.0, raw / 3.0))
    return round(score, 2)


def _keywords(text: str, category_hits: list[str]) -> list[str]:
    words = re.findall(r"[A-Za-z]{4,}", text or "")
    seen = []
    for w in words:
        lw = w.lower()
        if lw in category_hits or lw in ("double", "march", "twice", "again"):
            if lw not in seen:
                seen.append(lw)
    # Ensure at least the category hits are present.
    for h in category_hits:
        if h not in seen:
            seen.append(h)
    return seen[:6]
