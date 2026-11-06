"""Synthetic HTTP/authentication doubles; never live provider evidence."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from clavel.api.app import create_app
from clavel.api.inventory import (
    InventoryCursor, InventoryCursors, InventoryRuntime, policy_digest,
)
from clavel.intelligence.recommendations.inventory import FreshnessPolicy
from clavel.core.settings import Settings
from tests.test_openapi_contract import SPEC, validator


@pytest.fixture
def app():
    return create_app(
        settings=Settings(_env_file=None, app_env="test",
                          database_url="postgresql://synthetic:fake@localhost/synthetic"),
        inventory_runtime=InventoryRuntime(verify_bearer=lambda _: frozenset({"viewer"})),
    )


def assert_error_contract(response, status):
    operation = SPEC["paths"]["/v1/inventory"]["get"]
    schema = {"$ref": "#/components/schemas/Unavailable"} if status == 503 else {
        "$ref": "#/components/schemas/Error",
    }
    assert str(status) in operation["responses"]
    assert response.status_code == status
    validator(schema).validate(response.json())
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("authorization,roles,status", [
    (None, frozenset({"viewer"}), 401),
    ("Basic synthetic", frozenset({"viewer"}), 401),
    ("Bearer", frozenset({"viewer"}), 401),
    ("Bearer synthetic", None, 401),
    ("Bearer synthetic", frozenset(), 403),
    ("Bearer synthetic", frozenset({"operator"}), 403),
])
def test_authentication_precedes_database_access(app, authorization, roles, status):
    with TestClient(app) as client:
        app.state.inventory_runtime = InventoryRuntime(verify_bearer=lambda _: roles)
        app.state.database.session = Mock(side_effect=AssertionError("must not access storage"))
        headers = {} if authorization is None else {"Authorization": authorization}
        response = client.get("/v1/inventory", headers=headers)
        assert_error_contract(response, status)
        app.state.database.session.assert_not_called()


@pytest.mark.parametrize("failure", ["unconfigured", "provider_failure"])
def test_missing_or_failed_verifier_is_unavailable_and_redacted(app, failure):
    def broken_verifier(token):
        raise RuntimeError("synthetic-private-provider-detail")

    with TestClient(app) as client:
        app.state.inventory_runtime = InventoryRuntime(
            verify_bearer=broken_verifier if failure == "provider_failure" else None,
        )
        app.state.database.session = Mock()
        response = client.get("/v1/inventory", headers={"Authorization": "Bearer synthetic"})
        assert_error_contract(response, 503)
        assert response.json()["retryable"] is (failure == "provider_failure")
        assert "synthetic-private" not in response.text
        app.state.database.session.assert_not_called()


@pytest.mark.parametrize("query,status", [
    ("limit=0", 422), ("limit=101", 422), ("limit=abc", 422),
    ("cursor=", 422), ("cursor=" + "x" * 129, 422),
    ("cursor=synthetic-invalid", 400), ("cursor=v1:stock:1", 400),
    ("cursor=v1:skus:1", 400), ("cursor=v1:inventory:0", 400),
    ("cursor=v1:inventory:01", 400), ("cursor=v1:inventory:-1", 400),
    ("cursor=v1:inventory:9223372036854775808", 400),
    ("cursor=v1:inventory:١", 400),
])
def test_invalid_query_returns_contract_error_without_storage(app, query, status):
    with TestClient(app) as client:
        app.state.database.session = Mock()
        response = client.get("/v1/inventory?" + query,
                              headers={"Authorization": "Bearer synthetic"})
        assert_error_contract(response, status)
        app.state.database.session.assert_not_called()


def test_database_failure_is_unavailable_never_empty_success(app):
    @contextmanager
    def unavailable_session():
        raise psycopg.OperationalError("synthetic-private-database-detail")
        yield  # pragma: no cover

    with TestClient(app) as client:
        app.state.database.session = unavailable_session
        response = client.get("/v1/inventory", headers={"Authorization": "Bearer synthetic"})
    assert_error_contract(response, 503)
    assert response.json()["retryable"] is True
    assert "synthetic-private" not in response.text
    assert "items" not in response.json()


@pytest.mark.parametrize("change", [
    "expired", "future", "limit", "policy", "tampered", "different_app", "encoding",
])
def test_bound_cursor_rejected_before_storage(app, change):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    policy = FreshnessPolicy(timedelta(minutes=5))  # Synthetic fixture only.
    with TestClient(app) as client:
        codec = app.state.inventory_cursors
        if change == "different_app":
            codec = InventoryCursors()
        cursor = codec.encode(InventoryCursor(1, now, 1, b"s" * 16, policy_digest(policy)))
        clock = now
        limit = 1
        if change == "expired":
            clock += timedelta(minutes=5, microseconds=1)
        if change == "future":
            clock -= timedelta(microseconds=1)
        if change == "limit":
            limit = 2
        if change == "policy":
            policy = None
        if change == "tampered":
            cursor = ("A" if cursor[0] != "A" else "B") + cursor[1:]
        if change == "encoding":
            cursor += "="
        app.state.inventory_runtime = InventoryRuntime(
            verify_bearer=lambda _: frozenset({"viewer"}), freshness_policy=policy,
            clock=lambda: clock,
        )
        app.state.database.session = Mock()
        response = client.get("/v1/inventory", params={"limit": limit, "cursor": cursor},
                              headers={"Authorization": "Bearer synthetic"})
        assert_error_contract(response, 400)
        app.state.database.session.assert_not_called()


def test_inventory_openapi_has_bearer_role_and_contract_query_bounds(app):
    operation = app.openapi()["paths"]["/v1/inventory"]["get"]
    assert operation["operationId"] == "v1_list_inventory"
    assert operation["security"] == [{"BearerAuth": []}]
    assert operation["x-required-roles"] == ["viewer"]
    assert operation["x-availability"] == "local-validation-only"
    limit = next(p["schema"] for p in operation["parameters"] if p["name"] == "limit")
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 100, 20)


def test_inventory_has_no_write_operation(app):
    with TestClient(app) as client:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = client.request(method, "/v1/inventory")
            assert response.status_code == 405
            assert "GET" in response.headers["Allow"]


def test_review_only_inventory_patch_lints_and_preserves_other_operations():
    proposal = Path(__file__).resolve().parents[1] / "docs/openapi/p0036-inventory.proposal.json"
    proposed = copy.deepcopy(SPEC)
    for change in json.loads(proposal.read_text()):
        assert change["op"] in {"add", "replace"}
        assert change["path"].startswith("/paths/~1v1~1inventory/get/")
        parts = [part.replace("~1", "/").replace("~0", "~")
                 for part in change["path"].split("/")[1:]]
        parent = proposed
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        if isinstance(parent, list):
            parent[int(parts[-1])] = change["value"]
        else:
            parent[parts[-1]] = change["value"]
    validate(proposed)
    assert proposed["components"] == SPEC["components"]
    assert proposed["paths"]["/v1/inventory"]["get"]["parameters"] == \
        SPEC["paths"]["/v1/inventory"]["get"]["parameters"]
    for path in SPEC["paths"]:
        if path != "/v1/inventory":
            assert proposed["paths"][path] == SPEC["paths"][path]
    media = proposed["paths"]["/v1/inventory"]["get"]["responses"]["200"]["content"]["application/json"]
    for example in media["examples"].values():
        validator(media["schema"]).validate(example["value"])
