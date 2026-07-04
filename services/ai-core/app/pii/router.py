"""PII scrubber HTTP API (Feature 07)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.pii import scrubber

router = APIRouter()


class ScrubRequest(BaseModel):
    text: str
    traceId: str


class RehydrateRequest(BaseModel):
    text: str
    traceId: str


@router.post("/api/v1/internal/pii/scrub")
async def scrub(req: ScrubRequest) -> dict:
    return await scrubber.scrub(req.text, req.traceId)


@router.post("/api/v1/internal/pii/rehydrate")
async def rehydrate(req: RehydrateRequest) -> dict:
    return {"rehydrated": await scrubber.rehydrate(req.text, req.traceId)}
