"""Health check test stubs for ai-core."""

from fastapi.testclient import TestClient

from app.events.client import valkey_ping
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


def test_readiness_probe_reports_up_when_valkey_reachable():
    # Feature 01: readiness depends on Valkey — override the ping to isolate the test.
    app.dependency_overrides[valkey_ping] = lambda: True
    try:
        resp = client.get("/q/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "UP"
        assert {"name": "valkey", "status": "UP"} in body["checks"]
    finally:
        app.dependency_overrides.clear()


def test_readiness_probe_reports_down_when_valkey_unreachable():
    app.dependency_overrides[valkey_ping] = lambda: False
    try:
        resp = client.get("/q/health/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "DOWN"
        assert {"name": "valkey", "status": "DOWN"} in body["checks"]
    finally:
        app.dependency_overrides.clear()
