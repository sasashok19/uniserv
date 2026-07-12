"""Deduplication HTTP API (Feature 09).

Phase 1: level-1 detection — same identity + same category with an open ticket
→ append to existing; otherwise → new ticket. (Cluster/spam levels are Phase 2.)
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dedup.service import check_duplicate
from app.identity.db_client import DbWriterClient

logger = logging.getLogger("ai-core")

router = APIRouter()


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
        result = await check_duplicate(db, req.tenantId, req.masterId, req.category, trace_id=req.traceId)
    except httpx.HTTPError as exc:
        logger.error("dedup db-writer call failed traceId=%s: %s", req.traceId, exc)
        raise HTTPException(status_code=502, detail="db-writer unavailable") from exc

    if result["action"] == "append_to_existing":
        logger.info("dedup: appending to existing ticket traceId=%s existingTicketId=%s",
                    req.traceId, result["existingTicketId"])
    else:
        logger.info("dedup: no existing open ticket, new ticket traceId=%s", req.traceId)
    return result
