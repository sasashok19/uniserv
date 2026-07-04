"""Health check router for ai-core."""

from fastapi import APIRouter, Depends, Response

from app.events.client import valkey_ping

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
async def readiness(response: Response, valkey_ok: bool = Depends(valkey_ping)) -> dict:
    """Kubernetes readiness probe.

    Feature 01: readiness now depends on Valkey (the event bus). Returns 503
    when Valkey is unreachable so the service is pulled from rotation.
    """
    checks = [
        {"name": "ai-core", "status": "UP"},
        {"name": "valkey", "status": "UP" if valkey_ok else "DOWN"},
    ]
    if not valkey_ok:
        response.status_code = 503
        return {"status": "DOWN", "checks": checks}
    return {"status": "UP", "checks": checks}
