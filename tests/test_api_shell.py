"""Synthetic HTTP inputs and fake credentials; prove shell mechanics only."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from clavel.api.app import create_app
from clavel.core.errors import ApplicationError, ErrorCode
from clavel.core.settings import ConfigurationError, Settings

SYNTHETIC_SECRET = "synthetic-private-value"


@pytest.fixture
def app():
    """Synthetic local configuration; no database connection is opened."""
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://synthetic:fake@localhost/synthetic",
    )
    return create_app(settings=settings)


def test_health_and_factory_isolation(app):
    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "synthetic-request-1"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["X-Request-ID"] == "synthetic-request-1"
        assert app.state.settings.app_env == "test"
    assert create_app() is not app


@pytest.mark.parametrize("incoming", [None, "", "x" * 65, "synthetic private input"])
def test_request_ids_are_bounded_and_generated_per_request(app, incoming):
    headers = {} if incoming is None else {"X-Request-ID": incoming}
    with TestClient(app) as client:
        first = client.get("/health", headers=headers)
        second = client.get("/health", headers=headers)
    first_id = first.headers["X-Request-ID"]
    assert len(first_id) == 32
    assert int(first_id, 16) >= 0
    assert first_id != second.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("method", "path", "status", "code", "message"),
    [
        ("GET", "/synthetic-missing", 404, "not_found", "Not found"),
        ("POST", "/health", 405, "method_not_allowed", "Method not allowed"),
    ],
)
def test_router_errors_use_redacted_envelope(app, method, path, status, code, message):
    with TestClient(app) as client:
        response = client.request(method, path)
    assert response.status_code == status
    assert response.json() == {
        "error": {"code": code, "message": message},
        "request_id": response.headers["X-Request-ID"],
    }
    if status == 405:
        assert "GET" in response.headers["Allow"]


@pytest.mark.parametrize("kind", ["http", "unexpected", "application", "validation"])
def test_errors_redact_private_details_and_keep_correlation(app, kind):
    class SyntheticInput(BaseModel):
        count: int

    @app.post("/synthetic-error")
    async def synthetic_error(payload: SyntheticInput):
        if kind == "http":
            raise HTTPException(403, detail=SYNTHETIC_SECRET)
        if kind == "application":
            raise ApplicationError(ErrorCode.BAD_REQUEST)
        raise RuntimeError(SYNTHETIC_SECRET)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/synthetic-error",
            json={"count": SYNTHETIC_SECRET if kind == "validation" else 1},
            headers={"X-Request-ID": "synthetic-error-id"},
        )
    expected = {
        "http": (403, "http_error"),
        "unexpected": (500, "internal_error"),
        "application": (400, "bad_request"),
        "validation": (422, "validation_error"),
    }
    status, code = expected[kind]
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["request_id"] == "synthetic-error-id"
    assert response.headers["X-Request-ID"] == "synthetic-error-id"
    assert SYNTHETIC_SECRET not in response.text
    assert "traceback" not in response.text.lower()


def test_missing_configuration_fails_at_startup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError, match="database_url"):
        with TestClient(create_app()):
            pass
