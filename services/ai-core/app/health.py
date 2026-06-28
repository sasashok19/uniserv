"""Health check router for ai-core."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/v1/health")
async def health() -> dict:
    """Convenience health endpoint. Phase 1 scaffold: liveness only."""
    return {"service": "ai-core", "status": "UP"}


@router.get("/q/health/live")
async def liveness() -> dict:
    """Kubernetes liveness probe."""
    return {"status": "UP", "checks": [{"name": "ai-core", "status": "UP"}]}


@router.get("/q/health/ready")
async def readiness() -> dict:
    """Kubernetes readiness probe.

    PHASE_1: returns UP once the app is serving. Valkey connectivity is added
    as a readiness dependency in 01_EVENT_BUS.
    """
    return {"status": "UP", "checks": [{"name": "ai-core", "status": "UP"}]}
