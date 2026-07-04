"""Priority engine HTTP API (Feature 10)."""

from fastapi import APIRouter

from app.priority.engine import ScoreRequest, score

router = APIRouter()


@router.post("/api/v1/internal/priority/score")
async def priority_score(req: ScoreRequest) -> dict:
    return score(req)
