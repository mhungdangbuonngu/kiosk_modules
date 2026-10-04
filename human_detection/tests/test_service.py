from fastapi.testclient import TestClient
from test_engagement import config

from kiosk_vision.service import create_app


def test_health_and_empty_diagnostics():
    app = create_app(config(), "abc", run_vision=False)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["metrics"]["inference_backlog"] == 0
        assert client.get("/tracks").json() == []
        assert client.get("/events").json() == []

