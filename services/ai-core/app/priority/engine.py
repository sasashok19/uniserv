"""Priority scoring (Feature 10).

Weighted 0-10 score from six factors. Each factor is normalised to 0-10 then
combined by the Phase-1 weights below.
"""

from typing import Optional

from pydantic import BaseModel

# Factor weights (must sum to 1.0).
W_SENTIMENT = 0.25
W_SLA = 0.25
W_REPEAT = 0.20
W_CATEGORY = 0.15
W_CHANNEL = 0.10
W_VULNERABILITY = 0.05

# Channel severity (0-10), Phase 1.
CHANNEL_SEVERITY = {"whatsapp": 5.0, "email": 4.0}

# Category severity (0-10), default map (tenant config may override in later phases).
CATEGORY_SEVERITY = {
    "outage": 9.0, "billing": 6.0, "technical": 6.0,
    "service": 5.0, "product": 5.0, "other": 4.0,
}


class ScoreRequest(BaseModel):
    tenantId: str
    sentimentScore: float = 0.0          # -1.0 (very negative) .. 1.0
    slaHoursRemaining: Optional[float] = None
    slaHoursTotal: Optional[float] = None
    repeatContactCount: int = 0
    categoryLabel: Optional[str] = None
    channel: Optional[str] = None
    vulnerabilityKeywordsFound: list[str] = []


def score(req: ScoreRequest) -> dict:
    # Sentiment severity: -1 -> 10 (most severe), +1 -> 0.
    sentiment = _clamp((1.0 - req.sentimentScore) / 2.0 * 10.0)

    # SLA urgency: less time remaining -> more urgent.
    if req.slaHoursRemaining is not None and req.slaHoursTotal:
        sla = _clamp((1.0 - (req.slaHoursRemaining / req.slaHoursTotal)) * 10.0)
    else:
        sla = 0.0

    # Repeat contact: caps out at 3 prior contacts.
    repeat = _clamp(min(req.repeatContactCount, 3) / 3.0 * 10.0)

    category = CATEGORY_SEVERITY.get((req.categoryLabel or "other").lower(), 4.0)
    channel = CHANNEL_SEVERITY.get((req.channel or "").lower(), 4.0)
    vulnerability = 10.0 if req.vulnerabilityKeywordsFound else 0.0

    total = (
        W_SENTIMENT * sentiment
        + W_SLA * sla
        + W_REPEAT * repeat
        + W_CATEGORY * category
        + W_CHANNEL * channel
        + W_VULNERABILITY * vulnerability
    )
    total = round(_clamp(total), 1)
    return {"score": total, "label": label_for(total)}


def label_for(s: float) -> str:
    if s >= 8.0:
        return "critical"
    if s >= 6.0:
        return "high"
    if s >= 4.0:
        return "medium"
    return "low"


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))
