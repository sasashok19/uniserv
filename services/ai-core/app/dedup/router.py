"""Deduplication HTTP API (Feature 09).

Phase 1: level-1 detection — same identity + same category with an open ticket
→ append to existing; otherwise → new ticket. (Cluster/spam levels are Phase 2.)
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

router = APIRouter()

OPEN_STATUSES = "open,assigned,in_progress"


class DeduplicateRequest(BaseModel):
    tenantId: str
    masterId: str
    category: str
    subcategory: Optional[str] = None
    traceId: Optional[str] = None


@router.post("/api/v1/internal/deduplicate")
async def deduplicate(req: DeduplicateRequest) -> dict:
    db = DbWriterClient()
    try:
        existing = await db.list_tickets(
            req.tenantId, identityId=req.masterId, category=req.category, status=OPEN_STATUSES)
    except httpx.HTTPError as exc:
        logger.error("dedup db-writer call failed: %s", exc)
        raise HTTPException(status_code=502, detail="db-writer unavailable") from exc

    if existing:
        ticket = existing[0]
        return {
            "action": "append_to_existing",
            "existingTicketId": ticket.get("id"),
            "confidence": "high",
            "reason": "Same identity, same category, open ticket exists",
        }
    return {"action": "new_ticket", "confidence": "high"}
