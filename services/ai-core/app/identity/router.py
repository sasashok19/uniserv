"""Identity resolver HTTP API (Feature 03)."""

import logging

import httpx
from fastapi import APIRouter, HTTPException

from app.events.client import get_valkey
from app.events.publisher import BasePublisher
from app.identity.db_client import DbWriterClient
from app.identity.resolver import IdentityResolver, ResolveRequest

logger = logging.getLogger("ai-core")

router = APIRouter()


@router.post("/api/v1/identity/resolve")
async def resolve_identity(req: ResolveRequest) -> dict:
    publisher = BasePublisher(get_valkey(), req.tenantId)
    resolver = IdentityResolver(DbWriterClient(), publisher)
    try:
        return await resolver.resolve(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.error("db-writer call failed during identity resolve traceId=%s: %s", req.traceId, exc)
        raise HTTPException(status_code=502, detail="db-writer unavailable") from exc
