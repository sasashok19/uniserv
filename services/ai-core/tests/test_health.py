"""Health check test stubs for ai-core."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint_reports_up():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"service": "ai-core", "status": "UP"}


def test_liveness_probe_reports_up():
    resp = client.get("/q/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "UP"


def test_readiness_probe_reports_up():
    resp = client.get("/q/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "UP"
