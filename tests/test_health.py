"""Stage 0 smoke test.

Exists so that `make test` is meaningful from the first commit. A test suite
that starts empty tends to stay empty.
"""

from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_healthz_returns_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
